import json
import logging
import os
from flask import Flask, request, jsonify
import stripe
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import secretmanager

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
            # ✅ Create the product inside the club’s Stripe Express account
            stripe_product = stripe.Product.create(
                name=product['name'],
                description=f"Product for {club_name}",
                stripe_account=stripe_account_id  # ✅ Uses Express account
            )

            stripe_price = stripe.Price.create(
                unit_amount=int(product['price'] * 100),
                currency="eur",
                product=stripe_product.id,
                stripe_account=stripe_account_id  # ✅ Ensures price is linked to club
            )

            created_products.append({
                "name": product["name"],
                "stripe_product_id": stripe_product.id,
                "stripe_price_id": stripe_price.id,
                "price": product["price"]
            })

        return jsonify({"message": "Products created successfully", "products": created_products}), 201

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8087))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
