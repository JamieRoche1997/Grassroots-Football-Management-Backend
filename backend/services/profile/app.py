import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

# Initialise Flask app
app = Flask(__name__)
CORS(app)

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

        secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        response = client.access_secret_version(request={"name": secret_path})
        service_account_data = response.payload.data.decode("UTF-8")

        return json.loads(service_account_data)
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

# Collection reference
profiles_ref = db.collection("profile")

# Create Profile - POST /profile
@app.route("/profile", methods=["POST"])
def create_profile():
    try:
        data = request.json
        email = data["email"].strip().lower()

        profile_data = {
            "email": email,
            "name": data.get("name", ""),
            "position": data.get("position", ""),
            "role": data.get("role", "player"),
            "userRegistered": data.get("userRegistered", False),
            "clubName": data.get("clubName", ""),
            "ageGroup": data.get("ageGroup", ""),
            "division": data.get("division", ""),
            "createdAt": fs.SERVER_TIMESTAMP,
            "lastLogin": fs.SERVER_TIMESTAMP
        }

        profiles_ref.document(email).set(profile_data)

        return jsonify({"message": "Profile created successfully"}), 201

    except Exception as e:
        logger.error("Error creating profile for %s: %s", email, str(e))
        return jsonify({"error": "Internal server error"}), 500

# Get Profile - GET /profile/{email}
@app.route("/profile/<email>", methods=["GET"])
def get_profile(email):
    try:
        email = email.strip().lower()
        profile_doc = profiles_ref.document(email).get()

        if not profile_doc.exists:
            return jsonify({"error": "Profile not found"}), 404

        return jsonify(profile_doc.to_dict()), 200

    except Exception as e:
        logger.error("Error retrieving profile for %s: %s", email, str(e))
        return jsonify({"error": "Internal server error"}), 500

# Update Profile - PATCH /profile/{email}
@app.route("/profile/<email>", methods=["PATCH"])
def update_profile(email):
    try:
        email = email.strip().lower()
        update_data = request.json

        if not update_data:
            return jsonify({"error": "No fields provided to update"}), 400

        update_data["updatedAt"] = fs.SERVER_TIMESTAMP

        profiles_ref.document(email).update(update_data)

        return jsonify({"message": "Profile updated successfully"}), 200

    except Exception as e:
        logger.error("Error updating profile for %s: %s", email, str(e))
        return jsonify({"error": "Internal server error"}), 500

# Delete Profile - DELETE /profile/{email}
@app.route("/profile/<email>", methods=["DELETE"])
def delete_profile(email):
    try:
        email = email.strip().lower()

        profiles_ref.document(email).delete()

        return jsonify({"message": "Profile deleted successfully"}), 200

    except Exception as e:
        logger.error("Error deleting profile for %s: %s", email, str(e))
        return jsonify({"error": "Internal server error"}), 500

# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))  # Port 8090 for profile service
    logger.info("Starting profile service on port %d", port)
    app.run(host="0.0.0.0", port=port)
