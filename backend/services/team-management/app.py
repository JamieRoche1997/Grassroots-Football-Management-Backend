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
    """
    Create a new club or add the coach to an existing club.
    """
    try:
        data = request.json
        club_name = data.get("clubName")
        coach_email = data.get("coachEmail")
        county = data.get("county")
        age_groups = data.get("ageGroups")
        divisions = data.get("divisions")

        # Validate input
        if not club_name or not coach_email:
            return jsonify({"error": "Club name and coach email are required"}), 400

        # Check if the club already exists
        club_ref = db.collection("clubs").document(club_name)
        club_doc = club_ref.get()

        if club_doc.exists:
            # Add the coach to the existing club
            club_ref.update({"coaches": fs.ArrayUnion([coach_email])})
            return jsonify({"message": "Coach added to existing club"}), 200
        else:
            # Create a new club with the coach
            club_ref.set(
                {
                    "clubName": club_name,
                    "clubNameLower": club_name.lower(),
                    "coaches": [coach_email],
                    "county": county,
                    "ageGroups": [age_groups],
                    "divisions": [divisions],
                    "createdAt": fs.SERVER_TIMESTAMP,
                }
            )
            return jsonify({"message": "New club created"}), 201

    except KeyError as e:
        logging.error("Missing key in request data: %s", str(e))
        return jsonify({"error": "Missing key in request data"}), 400
    except ValueError as e:
        logging.error("Invalid value: %s", str(e))
        return jsonify({"error": "Invalid value"}), 400
    except Exception as e:
        logging.error("An unexpected error occurred: %s", str(e))
        return jsonify({"error": "An unexpected error occurred"}), 500


@app.route("/club/search", methods=["GET"])
def search_clubs():
    """
    Search for clubs based on club name, county, age group, or division.
    """
    try:
        # Get query parameters
        club_name = request.args.get("clubName", "").strip().lower()
        county = request.args.get("county", "").strip()
        age_group = request.args.get("ageGroup", "").strip()
        division = request.args.get("division", "").strip()

        # Start building the query
        clubs_ref = db.collection("clubs")
        queries = []

        # Partial match for club name using range queries
        if club_name:
            queries.append(("clubNameLower", ">=", club_name))
            queries.append(("clubNameLower", "<", club_name + "\uf8ff"))

        # Filter by county if provided
        if county:
            queries.append(("county", "==", county))

        # Filter by age group if provided
        if age_group:
            queries.append(("ageGroups", "array_contains", age_group))

        # Filter by division if provided
        if division:
            queries.append(("divisions", "array_contains", division))

        # Execute the query dynamically based on filters
        if not queries:
            # If no filters provided, return all clubs
            club_docs = clubs_ref.stream()
        else:
            # Dynamically chain query conditions
            query = clubs_ref
            for field, op, value in queries:
                query = query.where(field, op, value)
            club_docs = query.stream()

        # Return results as JSON
        clubs = [doc.to_dict() for doc in club_docs]
        return jsonify(clubs), 200

    except Exception as e:
        logging.error("Error searching clubs: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


@app.route("/club/join-request", methods=["POST"])
def join_club_request():
    """
    Handle a player's request to join a club.
    """
    try:
        data = request.json
        name = data.get("name")
        player_email = data.get("playerEmail")
        club_name = data.get("clubName")

        if not player_email or not club_name or name:
            return (
                jsonify({"error": "Name, player email and club name are required"}),
                400,
            )

        # Save the join request in Firestore
        join_requests_ref = db.collection("joinRequests")
        join_requests_ref.add(
            {
                "name": name,
                "playerEmail": player_email,
                "clubName": club_name,
                "status": "pending",
                "requestedAt": fs.SERVER_TIMESTAMP,
            }
        )

        return jsonify({"message": "Join request submitted successfully"}), 201

    except KeyError as e:
        logging.error("Missing key in request data: %s", str(e))
        return jsonify({"error": "Missing key in request data"}), 400
    except ValueError as e:
        logging.error("Invalid value: %s", str(e))
        return jsonify({"error": "Invalid value"}), 400


@app.route("/club/requests", methods=["GET"])
def get_join_requests():
    """
    Retrieve pending join requests for a specific club.
    """
    try:
        club_name = request.args.get("clubName")
        if not club_name:
            return jsonify({"error": "Club name is required"}), 400

        # Query for pending requests for the club
        join_requests_ref = (
            db.collection("joinRequests")
            .where("clubName", "==", club_name)
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

        if not player_email or not club_name:
            return jsonify({"error": "Player email and club name are required"}), 400

        # Update join request status to approved
        join_requests_ref = (
            db.collection("joinRequests")
            .where("playerEmail", "==", player_email)
            .where("clubName", "==", club_name)
        )
        for req in join_requests_ref.stream():
            req.reference.update({"status": "approved"})

        # Add player to club's players list
        club_ref = db.collection("clubs").document(club_name)
        club_ref.update({"players": fs.ArrayUnion([player_email])})

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

        if not player_email or not club_name:
            return jsonify({"error": "Player email and club name are required"}), 400

        # Update join request status to rejected
        join_requests_ref = (
            db.collection("joinRequests")
            .where("playerEmail", "==", player_email)
            .where("clubName", "==", club_name)
        )
        for req in join_requests_ref.stream():
            req.reference.update({"status": "rejected"})

        return jsonify({"message": "Join request rejected"}), 200

    except Exception as e:
        logging.error("Error rejecting join request: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8082)
    )  # Use PORT environment variable or default to 8082
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
