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


@app.route("/player/submit-rating", methods=["POST"])
def submit_player_rating():
    """
    Submit a new rating for a player.
    """
    try:
        data = request.json
        player_email = data.get("playerEmail")
        match_id = data.get("matchId")
        rated_by = data.get("ratedBy")

        rating_fields = [
            "overallPerformance",
            "passingAccuracy",
            "shootingAccuracy",
            "defensiveWorkRate",
            "attackingContributions",
            "teamwork",
            "skill",  
            "attitude"  
        ]

        if not player_email or not match_id or not rated_by:
            return jsonify({"error": "playerEmail, matchId, and ratedBy are required"}), 400

        rating = {field: data.get(field, 0) for field in rating_fields}
        rating["matchId"] = match_id
        rating["date"] = fs.SERVER_TIMESTAMP
        rating["ratedBy"] = rated_by

        player_ref = db.collection("player_ratings").document(player_email)
        player_doc = player_ref.get()

        if player_doc.exists:
            player_data = player_doc.to_dict()
            player_ratings = player_data.get("ratings", [])
            player_ratings.append(rating)

            total_votes = len(player_ratings)
            avg_rating = round(
                sum(r["overallPerformance"] for r in player_ratings) / total_votes, 1
            )

            player_ref.update({
                "ratings": player_ratings,
                "averageRating": avg_rating,
                "totalVotes": total_votes
            })
        else:
            player_ref.set({
                "playerEmail": player_email,
                "ratings": [rating],
                "averageRating": rating["overallPerformance"],
                "totalVotes": 1
            })

        return jsonify({"message": "Player rating submitted successfully"}), 201

    except Exception as e:
        logging.error("Error submitting player rating: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/player/get-ratings", methods=["GET"])
def get_player_ratings():
    """
    Get ratings for all players in a club.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return jsonify({"error": "Missing clubName, ageGroup, or division"}), 400

        player_ref = db.collection("player_ratings")
        query = player_ref.where("clubName", "==", club_name).where("ageGroup", "==", age_group).where("division", "==", division)

        players = []
        for doc in query.stream():
            player_data = doc.to_dict()
            players.append({
                "playerEmail": player_data.get("playerEmail"),
                "playerName": player_data.get("playerName"),
                "position": player_data.get("position"),
                "averageRating": player_data.get("averageRating", 0),
                "totalVotes": player_data.get("totalVotes", 0),
            })

        return jsonify(players), 200

    except Exception as e:
        logging.error("Error fetching player ratings: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8084)
    )  # Use PORT environment variable or default to 8084
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
