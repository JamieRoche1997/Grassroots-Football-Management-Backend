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


# Sign Up
@app.route("/signup", methods=["POST"])
def register():
    try:
        data = request.json
        email = data["email"]
        password = data["password"]
        name = data["name"]

        # Create user in Firebase Authentication
        user = auth.create_user(
            email=email,
            password=password,
            display_name=name,
        )

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
        return jsonify({"error": "Email already exists"}), 400
    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except TypeError as e:
        return jsonify({"error": f"Type error: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Value error: {str(e)}"}), 400


# Sign In
@app.route("/signin", methods=["POST"])
def sign_in():
    try:
        data = request.json
        id_token = data["idToken"]

        # Verify the ID token using Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token)
        user = auth.get_user(decoded_token["uid"])

        return (
            jsonify(
                {
                    "message": "User signed in successfully",
                    "firebase_uid": user.uid,
                    "email": user.email,
                }
            ),
            200,
        )

    except (InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError):
        return jsonify({"error": "Invalid or expired ID token"}), 401
    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Value error: {str(e)}"}), 400


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8080)
    )  # Use PORT environment variable or default to 8080
    logging.debug("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)