import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

app = Flask(__name__)
CORS(app)

# Logging Setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


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
        return json.loads(response.payload.data.decode("UTF-8"))
    except Exception as e:
        logger.error("Error loading secret: %s", str(e))
        raise


# Initialise Firebase
try:
    service_account_info = load_service_account_secret()
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    db = firestore.client()
    logger.debug("Firebase Admin initialised successfully")
except Exception as e:
    logger.error("Failed to initialise Firebase Admin: %s", str(e))
    raise


# Helper to get membership doc ref
def get_membership_ref(club_name, age_group, division, email):
    return (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("memberships")
        .document(email)
    )


# Create Membership
@app.route("/membership", methods=["POST"])
def create_membership():
    try:
        data = request.json
        club_name, age_group, division, email = (
            data["clubName"],
            data["ageGroup"],
            data["division"],
            data["email"].strip().lower(),
        )

        membership_data = {
            "email": email,
            "name": data.get("name", ""),
            "dob": data.get("dob", ""),
            "uid": data.get("uid", ""),
            "role": data.get("role", "player"),
            "position": data.get("position", ""),
            "userRegistered": data.get("userRegistered", False),
            "joinedAt": fs.SERVER_TIMESTAMP,
            "updatedAt": fs.SERVER_TIMESTAMP,
        }

        get_membership_ref(club_name, age_group, division, email).set(membership_data)

        return jsonify({"message": "Membership created successfully"}), 201

    except Exception as e:
        logger.error(f"Error creating membership: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Update Membership
@app.route("/membership", methods=["PATCH"])
def update_membership():
    try:
        data = request.json
        club_name, age_group, division, email = (
            data["clubName"],
            data["ageGroup"],
            data["division"],
            data["email"].strip().lower(),
        )

        update_data = {
            key: value
            for key, value in data.items()
            if key not in ["clubName", "ageGroup", "division", "email"]
        }
        update_data["updatedAt"] = fs.SERVER_TIMESTAMP

        get_membership_ref(club_name, age_group, division, email).update(update_data)

        return jsonify({"message": "Membership updated successfully"}), 200

    except Exception as e:
        logger.error(f"Error updating membership: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Get Membership (Single Player)
@app.route("/membership", methods=["GET"])
def get_membership():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")
        email = request.args.get("email").strip().lower()

        doc = get_membership_ref(club_name, age_group, division, email).get()

        if not doc.exists:
            return jsonify({"error": "Membership not found"}), 404

        return jsonify(doc.to_dict()), 200

    except Exception as e:
        logger.error(f"Error fetching membership: {e}")
        return jsonify({"error": "Internal server error"}), 500


# List All Players for a Team
@app.route("/membership/team", methods=["GET"])
def list_team_members():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        players = []
        memberships = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("memberships")
        )

        for doc in memberships.stream():
            member = doc.to_dict()
            if member.get("role") == "player":  # Only include players
                players.append(member)

        return jsonify(players), 200

    except Exception as e:
        logger.error(f"Error listing team members: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Delete Membership
@app.route("/membership", methods=["DELETE"])
def delete_membership():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")
        email = request.args.get("email").strip().lower()

        get_membership_ref(club_name, age_group, division, email).delete()

        return jsonify({"message": "Membership deleted successfully"}), 200

    except Exception as e:
        logger.error(f"Error deleting membership: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Start Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8089))
    logger.info(f"Starting membership service on port {port}")
    app.run(host="0.0.0.0", port=port)
