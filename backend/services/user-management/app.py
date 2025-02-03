import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import secretmanager

# Initialise Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def load_service_account_secret():
    """
    Load the Firebase service account credentials from Google Secret Manager.
    """
    try:
        client = secretmanager.SecretManagerServiceClient()

        project_id = "grassroots-football-management"
        secret_name = "firebase-service-account"
        secret_version = "latest"

        # Build the resource name of the secret version
        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )

        # Access the secret version
        response = client.access_secret_version(request={"name": secret_path})
        service_account_info = response.payload.data.decode("UTF-8")

        # Convert JSON string to a Python dictionary
        return json.loads(service_account_info)
    except Exception as e:
        logger.error("Error loading service account secret: %s", str(e))
        raise RuntimeError(f"Failed to load service account secret: {str(e)}") from e


# Initialise Firebase Admin with secret-loaded credentials
try:
    service_account_info = load_service_account_secret()
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    logger.debug("Firebase Admin initialised successfully")
except Exception as e:
    logger.error("Failed to initialise Firebase Admin: %s", str(e))
    raise

# Initialise Firestore
db = firestore.client()


@app.route("/user/update", methods=["POST"])
def update_user_profile():
    """
    Update a user's profile in Firestore.
    """
    try:
        data = request.json

        # Validate email
        if "email" not in data or not data["email"]:
            return jsonify({"error": "Email is required"}), 400

        email = data["email"]
        user_ref = db.collection("users").document(email)

        # Dynamically update Firestore with provided fields
        update_data = {key: value for key, value in data.items() if key != "email"}

        if not update_data:
            return jsonify({"error": "No fields provided for update"}), 400

        # Update Firestore document
        user_ref.update(update_data)
        logger.info("User profile updated for email: %s", email)

        return jsonify({"message": "User profile updated successfully"}), 200

    except KeyError as e:
        logger.error("Missing key: %s", str(e))
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except ValueError as e:
        logger.error("Invalid input: %s", str(e))
        return jsonify({"error": f"Invalid input: {str(e)}"}), 400


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8081)
    )  # Use PORT environment variable or default to 8081
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
