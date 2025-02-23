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
        secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
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

        return jsonify({
            "stripe_account_id": stripe_account_id if stripe_account_id else None
        }), 200

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
                return jsonify({"message": "Club already has a Stripe account", "stripe_account_id": club_data["stripe_account_id"]}), 200

        # ✅ Create an Express Account for the club
        account = stripe.Account.create(
            type="express",
            country="IE",  # Change based on club location
            email=email,
            capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
            business_type="company",
            business_profile={"name": club_name}
        )

        # ✅ Generate onboarding link for club
        account_link = stripe.AccountLink.create(
            account=account.id,
            refresh_url="http://localhost:5173/payments",  # Redirect if onboarding fails
            return_url="http://localhost:5173/payments",  # Redirect after success
            type="account_onboarding"
        )

        # 🔍 Store Stripe Account ID in Firestore
        db.collection("clubs").document(club_name).set({
            "stripe_account_id": account.id
        }, merge=True)

        return jsonify({"onboarding_url": account_link.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500


@app.route('/products/create', methods=['POST'])
def create_product():
    try:
        data = request.json
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not club_name or not age_group or not division:
            return jsonify({"error": "Club name, age group, and division are required"}), 400

        # 🔍 Retrieve club’s Stripe account ID
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        if not stripe_account_id:
            return jsonify({"error": "Club has not completed Stripe onboarding"}), 400

        created_products = []

        for product in data.get('products', []):
            product_name = product["name"]
            price_amount = int(product["price"] * 100)  # Convert to cents

            # 🔍 Step 1: Check if product already exists in Firestore under the correct age group & division
            existing_product_ref = (
                db.collection("clubs").document(club_name)
                .collection("teams").document(f"{age_group}_{division}")  # 🏆 Store under the specific team
                .collection("products").document(product_name)
            )
            existing_product = existing_product_ref.get()

            if existing_product.exists:
                existing_data = existing_product.to_dict()
                stripe_product_id = existing_data["stripe_product_id"]
                stripe_price_id = existing_data["stripe_price_id"]
            else:
                # 🆕 Step 2: Create a new product if it doesn’t exist
                stripe_product = stripe.Product.create(
                    name=product_name,
                    description=f"Product for {club_name} - {age_group} {division}",
                    metadata={"club": club_name, "ageGroup": age_group, "division": division},  # ✅ Save metadata
                    stripe_account=stripe_account_id  # ✅ Uses Express account
                )

                stripe_price = stripe.Price.create(
                    unit_amount=price_amount,
                    currency="eur",
                    product=stripe_product.id,
                    metadata={"club": club_name, "ageGroup": age_group, "division": division},  # ✅ Save metadata
                    stripe_account=stripe_account_id  # ✅ Ensures price is linked to club
                )

                stripe_product_id = stripe_product.id
                stripe_price_id = stripe_price.id

                # ✅ Step 3: Store in Firestore under the correct team
                existing_product_ref.set({
                    "stripe_product_id": stripe_product_id,
                    "stripe_price_id": stripe_price_id,
                    "price": product["price"],
                    "installmentMonths": product["installmentMonths"],
                    "ageGroup": age_group,
                    "division": division
                })

            created_products.append({
                "name": product_name,
                "stripe_product_id": stripe_product_id,
                "stripe_price_id": stripe_price_id,
                "price": product["price"],
                "ageGroup": age_group,
                "division": division
            })

        return jsonify({"message": "Products created successfully", "products": created_products}), 201

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500
    

@app.route('/products/list', methods=['GET'])
def list_products():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return jsonify({"error": "Club name, age group, and division are required"}), 400

        # 🔍 Retrieve club’s Firestore document
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        # 🔍 Retrieve all products for the specified age group & division
        products_ref = (
            db.collection("clubs").document(club_name)
            .collection("teams").document(f"{age_group}_{division}")
            .collection("products").stream()
        )

        products = []

        for product in products_ref:
            product_data = product.to_dict()
            products.append({
                "id": product.id,
                "name": product_data.get("name"),
                "price": product_data.get("price"),
                "installmentMonths": product_data.get("installmentMonths", None),
                "stripe_product_id": product_data.get("stripe_product_id"),
                "stripe_price_id": product_data.get("stripe_price_id"),
                "ageGroup": product_data.get("ageGroup"),
                "division": product_data.get("division"),
            })

        return jsonify({"products": products}), 200

    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500
    
@app.route("/stripe/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        data = request.json
        cart_items = data.get("cart", [])
        club_name = data.get("clubName")  # ✅ Ensure we know which club is making the sale

        if not club_name or not cart_items:
            return jsonify({"error": "Club name and cart items are required"}), 400

        # ✅ Retrieve club’s Stripe Express account ID from Firestore
        club_ref = db.collection("clubs").document(club_name).get()
        if not club_ref.exists:
            return jsonify({"error": "Club not found"}), 404

        club_data = club_ref.to_dict()
        stripe_account_id = club_data.get("stripe_account_id")

        if not stripe_account_id:
            return jsonify({"error": "Club has not completed Stripe onboarding"}), 400

        # ✅ Create line items for Stripe Checkout
        line_items = [
            {
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": item["product"]["name"]},
                    "unit_amount": int(item["product"]["price"] * 100),  # Convert to cents
                },
                "quantity": item["quantity"],
            }
            for item in cart_items
        ]

        # ✅ Create Stripe Checkout Session (For Connected Accounts)
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            success_url="http://localhost:5173/payments/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://localhost:5173/payments/cancel",
            line_items=line_items,
            stripe_account=stripe_account_id,  # ✅ Uses Club's Stripe Express Account
            transfer_data={  # ✅ Ensures payment is sent to the club
                "destination": stripe_account_id
            }
        )

        return jsonify({"checkoutUrl": session.url})

    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")
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

    return jsonify({"status": "success"}), 200


def handle_successful_payment(session):
    """Process successful payment, update Firestore, and notify the user."""
    try:
        customer_email = session["customer_email"]  # ✅ Get user email
        metadata = session["metadata"]  # ✅ Retrieve stored metadata
        club_name = metadata.get("clubName")
        age_group = metadata.get("ageGroup")
        division = metadata.get("division")

        # ✅ Find user in Firestore by email
        user_ref = db.collection("users").where("email", "==", customer_email).limit(1)
        user_docs = user_ref.stream()

        for doc in user_docs:
            user_id = doc.id  # Get the document ID
            user_data = doc.to_dict()

            # ✅ Update user document to mark as paid
            db.collection("users").document(user_id).update({
                "membershipPaid": True,
                "lastPaymentDate": fs.SERVER_TIMESTAMP
            })

            # ✅ Add payment record in Firestore
            payment_ref = db.collection("payments").document()
            payment_ref.set({
                "userId": user_id,
                "email": customer_email,
                "amount": session["amount_total"] / 100,  # Convert from cents
                "currency": session["currency"],
                "status": "completed",
                "club": club_name,
                "ageGroup": age_group,
                "division": division,
                "timestamp": fs.SERVER_TIMESTAMP
            })

    except Exception as e:
        logger.error("Error processing payment: %s", str(e))



# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8087))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
