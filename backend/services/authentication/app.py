import json
import os
import logging
from flask import Flask, request, jsonify
from firebase_admin import auth, credentials, firestore, initialize_app
from firebase_admin.auth import (
    InvalidIdTokenError,
    ExpiredIdTokenError,
    RevokedIdTokenError,
)
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

# Initialise Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.DEBUG)


def load_service_account_secret():
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
        service_account_data = response.payload.data.decode("UTF-8")

        # Convert JSON string to a Python dictionary
        return json.loads(service_account_data)
    except Exception as e:
        logging.error("Error loading service account secret: %s", str(e))
        raise RuntimeError(f"Failed to load service account secret: {str(e)}") from e


# Initialise Firebase Admin with secret-loaded credentials
try:
    service_account_info = load_service_account_secret()
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    logging.debug("Firebase Admin initialised successfully")
except Exception as e:
    logging.error("Failed to initialise Firebase Admin: %s", str(e))
    raise

# Initialise Firestore
db = firestore.client()

# Collection reference
users_ref = db.collection("users")

@app.route("/auth/create", methods=["POST"])
def create_auth_user():
    try:
        data = request.json
        email = data["email"].strip().lower()
        password = data["password"]

        # Create user in Firebase Authentication only
        user_record = auth.create_user(
            email=email,
            password=password,
        )

        user_data = {
            "uid": user_record.uid,
            "email": email,
        }

        users_ref.document(email).set(user_data)

        return jsonify({
            "message": "User created in Firebase Authentication",
            "uid": user_record.uid,
            "email": email,
        }), 201

    except auth.EmailAlreadyExistsError:
        return jsonify({"error": "Email already exists"}), 400
    except Exception as e:
        logging.error("Error creating auth user: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500

# Create User - POST /user
@app.route("/user", methods=["POST"])
def create_user():
    try:
        data = request.json
        email = data["email"].strip().lower()

        user_data = {
            "email": email,
            "uid": data.get("uid", ""),
        }

        users_ref.document(email).set(user_data)

        return jsonify({"message": "User created successfully"}), 201

    except KeyError as e:
        logging.error("Key error: %s", str(e))
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except ValueError as e:
        logging.error("Value error: %s", str(e))
        return jsonify({"error": f"Value error: {str(e)}"}), 400
    except Exception as e:
        logging.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Login - POST /auth/login
@app.route("/auth/login", methods=["POST"])
def login():
    try:
        data = request.json
        id_token = data["idToken"]

        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token.get("uid")
        email = decoded_token.get("email").strip().lower()

        user_doc = users_ref.document(email).get()

        if not user_doc.exists:
            return jsonify({"error": "User not found in Firestore"}), 404

        return jsonify({
            "message": "Login successful",
            "uid": uid,
            "email": email,
        }), 200

    except (InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError):
        return jsonify({"error": "Invalid or expired ID token"}), 401
    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Value error: {str(e)}"}), 400

# Get User - GET /auth/{email}
@app.route("/auth/<email>", methods=["GET"])
def get_user(email):
    try:
        email = email.strip().lower()

        user_doc = users_ref.document(email).get()

        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()

        return jsonify({
            "uid": user_data.get("uid"),
            "email": user_data.get("email"),
        }), 200

    except auth.UserNotFoundError:
        return jsonify({"error": "User not found in Firebase Auth"}), 404


# Update User - PATCH /auth/{email}
@app.route("/auth/<email>", methods=["PATCH"])
def update_user(email):
    try:
        email = email.strip().lower()
        update_data = request.json

        if "uid" not in update_data:
            return jsonify({"error": "UID is required"}), 400

        users_ref.document(email).update({
            "uid": update_data["uid"],
        })

        return jsonify({"message": "User UID updated successfully"}), 200

    except Exception as e:
        logging.error("Error updating user: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Delete User - DELETE /auth/{email}
@app.route("/auth/<email>", methods=["DELETE"])
def delete_user(email):
    try:
        email = email.strip().lower()

        user_doc = users_ref.document(email).get()

        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        uid = user_data.get("uid")

        # Delete from Firebase Auth
        auth.delete_user(uid)

        # Delete from Firestore
        users_ref.document(email).delete()

        return jsonify({"message": "User deleted successfully"}), 200

    except auth.UserNotFoundError:
        return jsonify({"error": "User not found in Firebase Auth"}), 404


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8080)
    )  # Use PORT environment variable or default to 8080
    logging.debug("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)