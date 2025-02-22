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

@app.route('/api/products/create', methods=['POST'])
def create_product():
    try:
        data = request.json
        products = data.get('products', [])

        created_products = []

        for product in products:
            # Step 1: Create a Product in Stripe
            stripe_product = stripe.Product.create(
                name=product['name'],
                description="Automatically created product in Stripe",
            )

            # Step 2: Create a Price for the Product in Stripe
            stripe_price = stripe.Price.create(
                unit_amount=int(product['price'] * 100),  # Stripe requires price in cents
                currency="eur",
                product=stripe_product.id,
                recurring={"interval": "month"} if product["installmentMonths"] else None,
            )

            created_products.append({
                "name": product["name"],
                "stripe_product_id": stripe_product.id,
                "stripe_price_id": stripe_price.id,
                "price": product["price"],
                "installmentMonths": product["installmentMonths"]
            })

        return jsonify({"message": "Products created successfully", "products": created_products}), 201

    except stripe.error.StripeError as e:
        return jsonify({"error": "Stripe error: " + str(e)}), 500
    except KeyError as e:
        return jsonify({"error": "Missing key: " + str(e)}), 400
    except ValueError as e:
        return jsonify({"error": "Invalid value: " + str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8087))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
