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
from google.cloud import secretmanager

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

        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )

        response = client.access_secret_version(request={"name": secret_path})
        service_account_data = response.payload.data.decode("UTF-8")

        return json.loads(service_account_data)
    except Exception as e:
        logging.error("Error loading service account secret: %s", str(e))
        raise RuntimeError(f"Failed to load service account secret: {str(e)}") from e


# Initialise Firebase Admin
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


# Helper function for standardized error responses
def error_response(message, status_code):
    return jsonify({"error": message}), status_code


### Sign Up
@app.route("/signup", methods=["POST"])
def register():
    try:
        data = request.json
        email = data.get("email")
        password = data.get("password")
        name = data.get("name")

        if not email or not password or not name:
            return error_response("Missing required fields", 400)

        user = auth.create_user(email=email, password=password, display_name=name)

        return (
            jsonify(
                {
                    "message": "User registered successfully",
                    "firebase_uid": user.uid,
                    "email": email,
                    "name": name,
                }
            ),
            201,
        )

    except auth.EmailAlreadyExistsError:
        return error_response("Email already exists", 400)
    except Exception as e:
        logging.error("Unexpected error: %s", str(e))
        return error_response("Internal server error", 500)


### Sign In
@app.route("/signin", methods=["POST"])
def sign_in():
    try:
        data = request.json
        id_token = data.get("idToken")

        if not id_token:
            return error_response("Missing ID token", 400)

        decoded_token = auth.verify_id_token(id_token)
        user = auth.get_user(decoded_token["uid"])

        # Fetch user role from Firestore
        user_doc = db.collection("users").document(user.email).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}

        return (
            jsonify(
                {
                    "message": "User signed in successfully",
                    "firebase_uid": user.uid,
                    "email": user.email,
                    "role": user_data.get("role", "player"),
                }
            ),
            200,
        )

    except (InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError):
        return error_response("Invalid or expired ID token", 401)
    except Exception as e:
        logging.error("Sign-in error: %s", str(e))
        return error_response("Internal server error", 500)


### Refresh Token
@app.route("/refresh-token", methods=["POST"])
def refresh_token():
    try:
        data = request.json
        id_token = data.get("idToken")

        if not id_token:
            return error_response("Missing ID token", 400)

        decoded_token = auth.verify_id_token(id_token, check_revoked=True)
        user = auth.get_user(decoded_token["uid"])
        new_token = auth.create_custom_token(user.uid).decode("utf-8")

        return jsonify({"newToken": new_token}), 200

    except Exception as e:
        logging.error("Error refreshing token: %s", str(e))
        return error_response("Internal server error", 500)


### Logout (Revoke Token)
@app.route("/logout", methods=["POST"])
def logout():
    try:
        data = request.json
        id_token = data.get("idToken")

        if not id_token:
            return error_response("Missing ID token", 400)

        decoded_token = auth.verify_id_token(id_token)
        auth.revoke_refresh_tokens(decoded_token["uid"])

        return jsonify({"message": "User logged out successfully"}), 200

    except Exception as e:
        logging.error("Error revoking token: %s", str(e))
        return error_response("Internal server error", 500)


### Password Reset
@app.route("/password-reset", methods=["POST"])
def password_reset():
    try:
        data = request.json
        email = data.get("email")

        if not email:
            return error_response("Missing email", 400)

        auth.generate_password_reset_link(email)
        return jsonify({"message": "Password reset email sent"}), 200

    except Exception as e:
        logging.error("Error sending password reset email: %s", str(e))
        return error_response("Internal server error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.debug("Starting auth-service on port %d", port)
    app.run(host="0.0.0.0", port=port)
