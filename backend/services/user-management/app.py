import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

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


# Create Firestore user
def create_firestore_user(user_data):
    try:
        user_ref = db.collection("users").document(user_data["email"])
        user_ref.set(
            {
                "uid": user_data["uid"],
                "name": user_data["name"],
                "email": user_data["email"],
                "role": user_data["role"],
                "position": user_data.get("position", ""),
                "clubName": user_data.get("clubName", ""), 
                "ageGroup": user_data.get("ageGroup", ""), 
                "division": user_data.get("division", ""),  
                "userRegistered": user_data.get("userRegistered", False),
            }
        )
    except Exception as e:
        logging.error("Failed to create Firestore user: %s", str(e))
        raise RuntimeError(f"Failed to create Firestore user: {str(e)}") from e


@app.route("/user/create", methods=["POST"])
def create_user_profile():
    try:
        data = request.json
        uid = data["uid"]
        email = data["email"]
        name = data["name"]
        role = data.get("role", "player")
        posistion = data.get("position", "")
        club_name = data.get("clubName", "")
        age_group = data.get("ageGroup", "")
        division = data.get("division", "")
        userRegistered = data.get("userRegistered", False)

        # Store user information in Firestore
        user_data = {
            "uid": uid,
            "name": name,
            "email": email,
            "role": role,
            "position": posistion,
            "clubName": club_name,
            "ageGroup": age_group,
            "division": division,
            "userRegistered": userRegistered,
        }
        create_firestore_user(user_data)

        return jsonify({"message": "User created successfully"}), 201

    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except TypeError as e:
        return jsonify({"error": f"Type error: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Value error: {str(e)}"}), 400


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


@app.route("/user/check", methods=["GET"])
def check_user_exists():
    """
    Check if a user exists in Firestore based on their email.
    """
    try:
        email = request.args.get("email")
        if not email:
            return jsonify({"error": "Email is required"}), 400

        user_ref = db.collection("users").document(email)
        user_doc = user_ref.get()

        if user_doc.exists:
            return jsonify({"exists": True, "message": "User already exists"}), 200
        else:
            return jsonify({"exists": False}), 200

    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/user/club-info", methods=["GET"])
def get_user_club_info():
    """
    Get the club name associated with a user's email.
    """
    try:
        email = request.args.get("email")
        if not email:
            return jsonify({"error": "Email is required"}), 400

        user_ref = db.collection("users").document(email)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            return (
                jsonify(
                    {
                        "clubName": user_data.get("clubName"),
                        "ageGroup": user_data.get("ageGroup"),
                        "division": user_data.get("division"),
                        "role": user_data.get("role"),
                    }
                ),
                200,
            )
        else:
            return jsonify({"error": "User not found"}), 404

    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500
    

@app.route('/user/update-match-event', methods=['POST'])
def update_user_match_event():
    """
    Append a match event count to the player's document in Firestore.
    """
    try:
        data = request.json
        player_name = data.get('playerEmail')
        event_type = data.get('type')

        if not player_name or not event_type:
            return jsonify({"error": "playerEmail and type are required"}), 400

        user_ref = db.collection('users').document(player_name)
        user = user_ref.get()

        if not user.exists:
            return jsonify({"error": "Player not found"}), 404

        update_data = {}

        if event_type == "goal":
            update_data["goals"] = fs.Increment(1)
        elif event_type == "assist":
            update_data["assists"] = fs.Increment(1)
        elif event_type == "yellowCard":
            update_data["yellowCards"] = fs.Increment(1)
        elif event_type == "redCard":
            update_data["redCards"] = fs.Increment(1)
        elif event_type == "injury":
            update_data["isInjured"] = True  # Flag player as injured

        user_ref.update(update_data)

        return jsonify({"message": f"{event_type} recorded successfully for player"}), 200

    except Exception as e:
        logging.error("Error updating user match event: %s", e)
        return jsonify({"error": "Internal server error"}), 500



# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8081)
    )  # Use PORT environment variable or default to 8081
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
