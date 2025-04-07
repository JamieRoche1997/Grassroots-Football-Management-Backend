import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, initialize_app, firestore
from google.cloud import firestore as fs, secretmanager
from flask_cors import CORS

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


@app.route("/club/create-join", methods=["POST"])
def create_or_join_club():
    try:
        data = request.json
        club_name = data.get("clubName")
        coach_email = data.get("coachEmail")
        county = data.get("county")

        # Convert to arrays if they are strings
        age_groups = data.get("ageGroups", [])
        divisions = data.get("divisions", [])

        if isinstance(age_groups, str):
            age_groups = [age.strip() for age in age_groups.split(",")]

        if isinstance(divisions, str):
            divisions = [division.strip() for division in divisions.split(",")]

        if not club_name or not coach_email:
            return jsonify({"error": "Club name and coach email are required"}), 400

        # Check if the club exists
        club_ref = db.collection("clubs").document(club_name)
        club_doc = club_ref.get()

        if club_doc.exists:
            current_data = club_doc.to_dict()
            existing_teams = current_data.get("teams", [])

            # Determine which teams to add
            new_teams = [
                {"ageGroup": age_group, "division": division}
                for age_group in age_groups
                for division in divisions
                if {"ageGroup": age_group, "division": division} not in existing_teams
            ]

            # Update with new teams and coaches
            updates = {
                "coaches": fs.ArrayUnion([coach_email]),
                "teams": fs.ArrayUnion(new_teams),
            }
            club_ref.update(updates)
            return jsonify({"message": "Coach added with updated teams"}), 200
        else:
            # Create new club with initial teams
            teams = [
                {"ageGroup": age_group, "division": division}
                for age_group in age_groups
                for division in divisions
            ]
            club_ref.set(
                {
                    "clubName": club_name,
                    "clubNameLower": club_name.lower(),
                    "coaches": [coach_email],
                    "county": county,
                    "teams": teams,
                    "createdAt": fs.SERVER_TIMESTAMP,
                }
            )
            return jsonify({"message": "New club created"}), 201

    except Exception as e:
        logging.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/search", methods=["GET"])
def search_clubs():
    try:
        club_name = request.args.get("clubName", "").strip().lower()
        county = request.args.get("county", "").strip()
        age_group = request.args.get("ageGroup", "").strip()
        division = request.args.get("division", "").strip()

        query = db.collection("clubs")
        if club_name:
            query = query.where("clubNameLower", ">=", club_name).where(
                "clubNameLower", "<", club_name + "\uf8ff"
            )
        if county:
            query = query.where("county", "==", county)

        clubs = []
        for doc in query.stream():
            club_data = doc.to_dict()
            filtered_teams = [
                team
                for team in club_data.get("teams", [])
                if (not age_group or team["ageGroup"] == age_group)
                and (not division or team["division"] == division)
            ]

            if filtered_teams:
                clubs.append(
                    {
                        "clubName": club_data["clubName"],
                        "county": club_data["county"],
                        "teams": filtered_teams,
                    }
                )

        return jsonify(clubs), 200

    except Exception as e:
        logging.error("Error searching clubs: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/join-request", methods=["POST"])
def join_club_request():
    try:
        data = request.json
        name = data.get("name")
        player_email = data.get("playerEmail")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if (
            not player_email
            or not club_name
            or not name
            or not age_group
            or not division
        ):
            return (
                jsonify(
                    {
                        "error": "Name, player email, club name, age group, and division are required"
                    }
                ),
                400,
            )

        join_requests_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("joinRequests")
        )
        join_requests_ref.add(
            {
                "name": name,
                "playerEmail": player_email,
                "status": "pending",
                "requestedAt": fs.SERVER_TIMESTAMP,
            }
        )

        return jsonify({"message": "Join request submitted successfully"}), 201

    except Exception as e:
        logging.error("Unexpected error: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/requests", methods=["GET"])
def get_join_requests():
    """
    Retrieve pending join requests for a specific club, age group, and division.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return (
                jsonify({"error": "Club name, age group, and division are required"}),
                400,
            )

        # Query for pending requests for the club, age group, and division
        join_requests_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("joinRequests")
            .where("status", "==", "pending")
        )
        requests = [req.to_dict() for req in join_requests_ref.stream()]
        return jsonify(requests), 200

    except Exception as e:
        logging.error("Error retrieving join requests: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/requests/approve", methods=["POST"])
def approve_join_request():
    """
    Approve a player's join request and add them to the club's players list.
    """
    try:
        data = request.json
        player_email = data.get("playerEmail")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not player_email or not club_name:
            return jsonify({"error": "Player email and club name are required"}), 400

        # Update join request status to approved
        join_requests_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("joinRequests")
            .where("playerEmail", "==", player_email)
        )
        for req in join_requests_ref.stream():
            req.reference.update({"status": "approved"})

        return jsonify({"message": "Player added to the club"}), 200

    except Exception as e:
        logging.error("Error approving join request: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/requests/reject", methods=["POST"])
def reject_join_request():
    """
    Reject a player's join request.
    """
    try:
        data = request.json
        player_email = data.get("playerEmail")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not player_email or not club_name:
            return jsonify({"error": "Player email and club name are required"}), 400

        # Update join request status to rejected
        join_requests_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("joinRequests")
            .where("playerEmail", "==", player_email)
            .where("clubName", "==", club_name)
        )
        for req in join_requests_ref.stream():
            req.reference.update({"status": "rejected"})

        return jsonify({"message": "Join request rejected"}), 200

    except Exception as e:
        logging.error("Error rejecting join request: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/players", methods=["GET"])
def get_players():
    """
    Retrieve players associated with a club, age group, and division.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return (
                jsonify({"error": "Club name, age group, and division are required"}),
                400,
            )

        # Query users collection for players matching the criteria
        membership_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("memberships")
        )
        players_query = (
            membership_ref.where("role", "==", "player")
            .where("clubName", "==", club_name)
            .where("ageGroup", "==", age_group)
            .where("division", "==", division)
            .stream()
        )

        # Convert query results to a list of dictionaries
        players = [player.to_dict() for player in players_query]

        return jsonify(players), 200

    except Exception as e:
        logger.error("Error retrieving players: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8082)
    )  # Use PORT environment variable or default to 8082
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
