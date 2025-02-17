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

@app.route("/match/submit-rating", methods=["POST"])
def submit_match_rating():
    """
    Submit a new rating for a match.
    """
    try:
        data = request.json
        logging.info("Received match rating data: %s", json.dumps(data, indent=4))

        match_id = data.get("matchId")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")
        rated_by = data.get("ratedBy")

        rating_fields = [
            "overallQuality",
            "refereeingPerformance",
            "homeTeamPerformance",
            "awayTeamPerformance",
            "sportsmanship",
            "crowdAtmosphere"
        ]

        # Validate required fields
        missing_fields = [field for field in ["matchId", "ratedBy"] if not data.get(field)]
        if missing_fields:
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

        # Validate rating fields (ensure numbers between 1 and 10)
        invalid_fields = [field for field in rating_fields if not isinstance(data.get(field, 0), int) or not (1 <= data[field] <= 10)]
        if invalid_fields:
            return jsonify({"error": f"Invalid rating values: {', '.join(invalid_fields)}. Ratings must be between 1 and 10."}), 400

        rating = {field: data.get(field, 0) for field in rating_fields}
        rating["ratedBy"] = rated_by

        match_ref = db.collection("match_ratings").document(match_id)
        match_doc = match_ref.get()

        if match_doc.exists:
            match_data = match_doc.to_dict()
            match_ratings = match_data.get("ratings", [])
            match_ratings.append(rating)

            total_votes = len(match_ratings)
            avg_rating = round(sum(r["overallQuality"] for r in match_ratings) / total_votes, 1)

            match_ref.update({
                "clubName": club_name,
                "ageGroup": age_group,
                "division": division,
                "ratings": match_ratings,
                "averageRating": avg_rating,
                "totalVotes": total_votes,
                "updatedAt": fs.SERVER_TIMESTAMP
            })
        else:
            match_ref.set({
                "matchId": match_id,
                "clubName": club_name,
                "ageGroup": age_group,
                "division": division,
                "ratings": [rating],
                "averageRating": rating["overallQuality"],
                "totalVotes": 1,
                "createdAt": fs.SERVER_TIMESTAMP
            })

        return jsonify({"message": "Match rating submitted successfully"}), 201

    except Exception as e:
        logging.exception("Unexpected error submitting match rating")
        return jsonify({"error": str(e)}), 500

@app.route("/match/get-ratings", methods=["GET"])
def get_match_ratings():
    """
    Get ratings for all matches in a club.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return jsonify({"error": "Missing clubName, ageGroup, or division"}), 400

        match_ref = db.collection("match_ratings")
        query = match_ref.where("clubName", "==", club_name).where("ageGroup", "==", age_group).where("division", "==", division)

        matches = []
        for doc in query.stream():
            match_data = doc.to_dict()
            matches.append({
                "matchId": match_data.get("matchId"),
                "averageRating": match_data.get("averageRating", 0),
                "totalVotes": match_data.get("totalVotes", 0),
            })

        return jsonify(matches), 200

    except Exception as e:
        logging.error("Error fetching match ratings: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8085)
    )  # Use PORT environment variable or default to 8085
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
