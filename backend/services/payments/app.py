import json
import logging
import os
from flask import Flask, request, jsonify
import stripe
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

# Initialise Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def load_secret(secret_name):
    """Load a secret from Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = "grassroots-football-management"
        secret_version = "latest"

        # Build the resource name of the secret version
        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )
        response = client.access_secret_version(request={"name": secret_path})
        secret_value = response.payload.data.decode("UTF-8")

        return secret_value
    except Exception as e:
        logger.error("Error loading secret %s: %s", secret_name, str(e))
        raise RuntimeError(f"Failed to load secret {secret_name}: {str(e)}") from e


# Load Firebase service account
try:
    service_account_info = json.loads(load_secret("firebase-service-account"))
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    logger.debug("Firebase Admin initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Firebase Admin: %s", str(e))
    raise

# Load Stripe secret key
try:
    stripe_secret_key = load_secret("stripe-secret-key")
    stripe.api_key = stripe_secret_key
    logger.debug("Stripe API key loaded successfully")
except Exception as e:
    logger.error("Failed to load Stripe API key: %s", str(e))
    raise

# Initialise Firestore
db = firestore.client()


@app.route("/stripe/status", methods=["GET"])
def check_stripe_status():
    try:
        club_name = request.args.get("clubName")
        if not club_name:
            return jsonify({"error": "Club name is required"}), 400

        # 🔍 Retrieve the club’s Stripe account ID from Firestore
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        return (
            jsonify(
                {"stripe_account_id": stripe_account_id if stripe_account_id else None}
            ),
            200,
        )

    except ValueError as e:
        return jsonify({"error": "Invalid value: " + str(e)}), 400


@app.route("/stripe/connect", methods=["POST"])
def create_connect_account():
    try:
        data = request.json
        club_name = data.get("clubName")
        email = data.get("email")

        # 🔍 Check if the club already has a Stripe account
        club_ref = db.collection("clubs").document(club_name).get()
        if club_ref.exists:
            club_data = club_ref.to_dict()
            if "stripe_account_id" in club_data:
                return (
                    jsonify(
                        {
                            "message": "Club already has a Stripe account",
                            "stripe_account_id": club_data["stripe_account_id"],
                        }
                    ),
                    200,
                )

        # ✅ Create an Express Account for the club
        account = stripe.Account.create(
            type="express",
            country="IE",  # Change based on club location
            email=email,
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            business_type="company",
            business_profile={"name": club_name},
        )

        # ✅ Generate onboarding link for club
        account_link = stripe.AccountLink.create(
            account=account.id,
            refresh_url="https://grassroots-football-management.web.app/payments",  # Redirect if onboarding fails
            return_url="https://grassroots-football-management.web.app/payments",  # Redirect after success
            type="account_onboarding",
        )

        # 🔍 Store Stripe Account ID in Firestore
        db.collection("clubs").document(club_name).set(
            {"stripe_account_id": account.id}, merge=True
        )

        return jsonify({"onboarding_url": account_link.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500


@app.route("/products/create", methods=["POST"])
def create_product():
    try:
        data = request.json
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not club_name or not age_group or not division:
            return (
                jsonify({"error": "Club name, age group, and division are required"}),
                400,
            )

        # 🔍 Retrieve club’s Stripe account ID
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        if not stripe_account_id:
            return jsonify({"error": "Club has not completed Stripe onboarding"}), 400

        created_products = []

        for product in data.get("products", []):
            product_name = product["name"]
            total_price = float(product["price"])
            installment_months = product.get("installmentMonths")
            category = product.get("category", "other")
            is_membership = category == "membership"

            existing_product_ref = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("products")
                .document(product_name)
            )

            existing_product = existing_product_ref.get()

            if existing_product.exists:
                existing_data = existing_product.to_dict()
                stripe_product_id = existing_data["stripe_product_id"]
                stripe_price_id = existing_data["stripe_price_id"]
            else:
                # 🆕 Step 1: Create Stripe Product
                stripe_product = stripe.Product.create(
                    name=product_name,
                    description=f"Product for {club_name} - {age_group} {division}",
                    metadata={
                        "club": club_name,
                        "ageGroup": age_group,
                        "division": division,
                        "category": category,  # ✅ Store category in Stripe metadata
                        "isMembership": str(
                            is_membership
                        ).lower(),  # ✅ Store as string (Stripe metadata only supports strings)
                    },
                    stripe_account=stripe_account_id,
                )

                if installment_months and installment_months > 1:
                    # 🛠️ Step 2a: Create a recurring price for installments
                    monthly_price = round(total_price / installment_months, 2)
                    stripe_price = stripe.Price.create(
                        unit_amount=int(monthly_price * 100),
                        currency="eur",
                        recurring={"interval": "month"},
                        product=stripe_product.id,
                        metadata={
                            "club": club_name,
                            "ageGroup": age_group,
                            "division": division,
                            "installmentMonths": installment_months,
                            "category": category,  # ✅ Store category in Stripe metadata
                            "isMembership": str(is_membership).lower(),
                        },
                        stripe_account=stripe_account_id,
                    )
                else:
                    # 💰 Step 2b: Create a one-time price
                    stripe_price = stripe.Price.create(
                        unit_amount=int(total_price * 100),
                        currency="eur",
                        product=stripe_product.id,
                        metadata={
                            "club": club_name,
                            "ageGroup": age_group,
                            "division": division,
                            "category": category,  # ✅ Store category in Stripe metadata
                            "isMembership": str(is_membership).lower(),
                        },
                        stripe_account=stripe_account_id,
                    )

                stripe_product_id = stripe_product.id
                stripe_price_id = stripe_price.id

                # ✅ Step 3: Store in Firestore under the correct team
                existing_product_ref.set(
                    {
                        "name": product_name,
                        "stripe_product_id": stripe_product_id,
                        "stripe_price_id": stripe_price_id,
                        "price": total_price,
                        "installmentMonths": installment_months,
                        "category": category,  # ✅ Store category in Firestore
                        "isMembership": is_membership,  # ✅ Store membership flag
                    }
                )

            created_products.append(
                {
                    "name": product_name,
                    "stripe_product_id": stripe_product_id,
                    "stripe_price_id": stripe_price_id,
                    "price": total_price,
                    "installmentMonths": installment_months,
                    "category": category,  # ✅ Include in response
                    "isMembership": is_membership,  # ✅ Include in response
                }
            )

        return (
            jsonify(
                {
                    "message": "Products created successfully",
                    "products": created_products,
                }
            ),
            201,
        )

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/products/list", methods=["GET"])
def list_products():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return (
                jsonify({"error": "Club name, age group, and division are required"}),
                400,
            )

        # 🔍 Retrieve club’s Firestore document
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        # 🔍 Retrieve all products for the specified age group & division
        products_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("products")
            .stream()
        )

        products = []

        for product in products_ref:
            product_data = product.to_dict()
            products.append(
                {
                    "id": product.id,
                    "name": product_data.get("name"),
                    "price": product_data.get("price"),
                    "installmentMonths": product_data.get("installmentMonths", None),
                    "category": product_data.get("category"),
                    "isMembership": product_data.get("isMembership"),
                    "stripe_product_id": product_data.get("stripe_product_id"),
                    "stripe_price_id": product_data.get("stripe_price_id"),
                }
            )

        return jsonify({"products": products}), 200

    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/stripe/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        data = request.json
        cart_items = data.get("cart", [])
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")
        customer_email = data.get("customerEmail")

        if not club_name or not cart_items:
            return jsonify({"error": "Club name and cart items are required"}), 400

        # ✅ Retrieve club’s Stripe Express account ID
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        if not stripe_account_id:
            return jsonify({"error": "Club has not completed Stripe onboarding"}), 400

        line_items = []
        checkout_mode = "payment"  # Default to one-time payments
        has_subscription = False
        installment_months = None

        for item in cart_items:
            price_id = item.get("priceId")
            quantity = item.get("quantity", 1)

            if not price_id:
                return jsonify({"error": "Missing `priceId` in cart"}), 400

            # 🔍 Retrieve product details from Firestore
            product_ref = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("products")
                .document(item.get("id"))
                .get()
            )

            if not product_ref.exists:
                return jsonify({"error": f"Product {item.get('id')} not found"}), 400

            product_data = product_ref.to_dict()
            item_installment_months = product_data.get("installmentMonths")

            # 🛠️ If product has installments, switch to subscription mode
            if item_installment_months and item_installment_months > 1:
                checkout_mode = "subscription"
                has_subscription = True
                installment_months = (
                    item_installment_months  # Track installment duration
                )

            line_items.append(
                {
                    "price": price_id,
                    "quantity": quantity,
                }
            )

        # ✅ Create Stripe Checkout Session
        session_data = {
            "mode": checkout_mode,
            "success_url": "https://grassroots-football-management.web.app/payments/success",
            "cancel_url": "https://grassroots-football-management.web.app/payments/cancel",
            "line_items": line_items,
            "stripe_account": stripe_account_id,
            "metadata": {
                "clubName": club_name,
                "ageGroup": age_group,
                "division": division,
                "customerEmail": customer_email,
                "isSubscription": "true" if has_subscription else "false",
                "installmentMonths": (
                    str(installment_months) if has_subscription else "0"
                ),
            },
        }

        session = stripe.checkout.Session.create(**session_data)

        return jsonify({"checkoutUrl": session.url})

    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = load_secret("stripe-webhook-secret")  # ✅ Store securely

    try:
        # ✅ Verify the event came from Stripe
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    # ✅ Handle the event type
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        handle_successful_payment(session)  # ✅ Process the payment
        handle_subscription(session)  # ✅ Handle subscription payments

    return jsonify({"status": "success"}), 200


def handle_subscription(session):
    """Handles subscription-based purchases and creates a Subscription Schedule."""

    # ✅ Extract session ID
    session_id = session.get("id")
    club_name = session.get("metadata", {}).get("clubName")

    # ✅ Retrieve club’s Stripe Express account ID
    club_ref = db.collection("clubs").document(club_name).get()
    if not club_ref.exists:
        return jsonify({"error": "Club not found"}), 404

    club_data = club_ref.to_dict()
    stripe_account_id = club_data.get("stripe_account_id")

    try:
        # ✅ Fetch line items from the connected account
        line_items = stripe.checkout.Session.list_line_items(
            session_id, stripe_account=stripe_account_id
        )["data"]

        # ✅ Extract subscription details
        if (
            session.get("mode") == "subscription"
            and session.get("metadata", {}).get("isSubscription") == "true"
        ):
            subscription_id = session.get("subscription")
            installment_months = int(
                session.get("metadata", {}).get("installmentMonths", "0")
            )

            for item in line_items:
                price_id = item.get("price", "")
                quantity = item.get("quantity", 1)

            if subscription_id and installment_months > 0:
                # ✅ Create Subscription Schedule on the correct connected account
                subscription_schedule = stripe.SubscriptionSchedule.create(
                    from_subscription=subscription_id,
                    stripe_account=stripe_account_id,
                )

                subscription_schedule_id = subscription_schedule["id"]
                start_date = subscription_schedule["phases"][0]["start_date"]

                print(
                    f"✅ Subscription Schedule created for {subscription_schedule_id} on {stripe_account_id}"
                )

                stripe.SubscriptionSchedule.modify(
                    subscription_schedule_id,
                    end_behavior="cancel",
                    phases=[
                        {
                            "start_date": start_date,
                            "items": [
                                {
                                    "price": price_id,
                                    "quantity": quantity,
                                }
                            ],
                            "iterations": installment_months,
                        },
                    ],
                    stripe_account=stripe_account_id,
                )

    except stripe.error.StripeError as e:
        print(f"❌ Stripe API Error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected Error: {str(e)}")


def handle_successful_payment(session):
    """Process successful payment, update Firestore, and notify the user."""
    try:
        # ✅ Get customer email
        customer_email = session.get("customer_email") or session.get(
            "customer_details", {}
        ).get("email")

        # ✅ Retrieve metadata
        metadata = session.get("metadata", {})
        club_name = metadata.get("clubName")
        age_group = metadata.get("ageGroup")
        division = metadata.get("division")

        if not customer_email:
            logger.error("Customer email is missing from Stripe session.")
            return

        if not club_name:
            logger.error("Missing required metadata: clubName")
            return

        # ✅ Find user in Firestore by email
        user_ref = db.collection("users").where("email", "==", customer_email).limit(1)
        user_docs = list(user_ref.stream())

        if not user_docs:
            logger.error("User with email %s not found.", customer_email)
            return

        user_id = user_docs[0].id  # Get the document ID

        # ✅ Extract session ID
        session_id = session.get("id")

        # ✅ Retrieve club’s Stripe Express account ID
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        line_items = stripe.checkout.Session.list_line_items(
            session_id, stripe_account=stripe_account_id
        )["data"]

        membership_purchased = False
        purchased_items = []

        for item in line_items:
            price_id = item["price"]["id"]
            quantity = item.get("quantity", 1)

            # ✅ Find product details in Firestore
            product_query = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("products")
                .where("stripe_price_id", "==", price_id)
                .limit(1)
            )
            product_docs = list(product_query.stream())

            if not product_docs:
                logger.warning("Product with Stripe price ID %s not found.", price_id)
                continue

            product_data = product_docs[0].to_dict()
            product_name = product_data.get("name", "Unknown Product")
            category = product_data.get("category", "other")
            is_membership = product_data.get("isMembership", False)
            installment_months = product_data.get("installmentMonths")

            if is_membership:
                membership_purchased = True  # ✅ A membership was bought

            # ✅ Store each purchased item
            purchased_items.append(
                {
                    "productId": price_id,
                    "productName": product_name,
                    "category": category,
                    "quantity": quantity,
                    "isMembership": is_membership,
                    "installmentMonths": installment_months,
                    "totalPrice": session["amount_total"] / 100,
                }
            )

        # ✅ Update membership status only if a membership was bought
        if membership_purchased:
            (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("memberships")
                .document(customer_email)
                .update(
                    {
                        "membershipPaid": True,
                        "lastPaymentDate": firestore.SERVER_TIMESTAMP,
                    }
                )
            )

        # ✅ Store the payment record in Firestore
        payment_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("payments")
            .document(customer_email)
        )

        payment_ref.set(
            {
                "userId": user_id,
                "email": customer_email,
                "amount": session["amount_total"] / 100,  # Convert cents to EUR
                "currency": session["currency"],
                "status": "completed",
                "purchasedItems": purchased_items,  # ✅ Includes category & membership info
                "timestamp": fs.SERVER_TIMESTAMP,
            }
        )

        logger.info("✅ Payment successfully processed for %s", customer_email)

    except Exception as e:
        logger.error("Error processing payment: %s", str(e))


@app.route("/transactions/list", methods=["GET"])
def list_transactions():
    try:
        user_email = request.args.get("email")
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")
        if not user_email:
            return jsonify({"error": "User email is required"}), 400

        # 🔍 Retrieve transactions from Firestore
        transactions_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("payments")
            .where("email", "==", user_email)
            .order_by("timestamp", direction=fs.Query.DESCENDING)
            .stream()
        )

        transactions = []
        for doc in transactions_ref:
            transaction_data = doc.to_dict()

            transactions.append(
                {
                    "id": doc.id,
                    "amount": transaction_data.get("amount"),
                    "currency": transaction_data.get("currency"),
                    "status": transaction_data.get("status"),
                    "timestamp": transaction_data.get("timestamp").isoformat(),
                    "purchasedItems": transaction_data.get(
                        "purchasedItems", []
                    ),  # ✅ Include itemized purchases
                }
            )

        return jsonify({"transactions": transactions}), 200

    except Exception as e:
        logger.error("Error retrieving transactions: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/stripe/login-link", methods=["POST"])
def create_stripe_login_link():
    try:
        data = request.json
        club_name = data.get("clubName")

        if not club_name:
            return jsonify({"error": "Club name is required"}), 400

        # 🔍 Retrieve the club’s Stripe account ID from Firestore
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        if not stripe_account_id:
            return (
                jsonify({"error": "Club does not have a Stripe Express account"}),
                400,
            )

        # ✅ Generate login link for Stripe Express Dashboard
        login_link = stripe.Account.create_login_link(stripe_account_id)

        return jsonify({"url": login_link["url"]}), 200

    except stripe.error.StripeError as e:
        return jsonify({"error": f"Stripe error: {str(e)}"}), 500
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Get all payments - GET /payments
@app.route("/payments", methods=["GET"])
def get_payments():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not all([club_name, age_group, division]):
            return jsonify({"error": "Missing required query parameters"}), 400

        payments_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("payments")
            .stream()
        )

        payments = []
        for doc in payments_ref:
            payments_data = doc.to_dict()

            payments.append(
                {
                    "id": doc.id,
                    "amount": payments_data.get("amount"),
                    "currency": payments_data.get("currency"),
                    "status": payments_data.get("status"),
                    "timestamp": payments_data.get("timestamp").isoformat(),
                    "purchasedItems": payments_data.get("purchasedItems", []),
                }
            )

        return jsonify({"payments": payments}), 200

    except Exception as e:
        logger.error("Error retrieving payments: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8087))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
