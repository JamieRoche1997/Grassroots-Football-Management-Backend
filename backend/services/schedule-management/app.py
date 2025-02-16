import json
import logging
import os
import uuid
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


@app.route('/schedule/matches', methods=['GET'])
def get_matches():
    """
    Retrieve matches for a specific month, age group, and division.
    """
    try:
        month = request.args.get('month')  # Format: yyyy-MM
        club_name = request.args.get('clubName')
        age_group = request.args.get('ageGroup')
        division = request.args.get('division')

        if not month or not age_group or not division:
            return jsonify({"error": "Month, age group, and division are required"}), 400

        matches_ref = db.collection('matches')
        query = matches_ref.where('ageGroup', '==', age_group).where('division', '==', division)

        # Filter by month
        matches = [
            match.to_dict()
            for match in query.stream()
            if match.to_dict()['date'].startswith(month) and
               (match.to_dict().get('homeTeam') == club_name or match.to_dict().get('awayTeam') == club_name)
        ]

        return jsonify(matches), 200

    except Exception as e:
        logging.error("Error fetching matches: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/schedule/add-fixture', methods=['POST'])
def add_fixture():
    """
    Add a new fixture to the schedule.
    """
    try:
        data = request.json
        fixture = {
            "matchId": str(uuid.uuid4()),
            "homeTeam": data['homeTeam'],
            "awayTeam": data['awayTeam'],
            "ageGroup": data['ageGroup'],
            "division": data['division'],
            "date": data['date'],
            "result": None,  # Result will be null initially
            "createdBy": data['createdBy']
        }
        db.collection('matches').document(fixture['matchId']).set(fixture)
        return jsonify({"message": "Fixture added successfully"}), 201

    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error adding fixture: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/schedule/update-result', methods=['PUT'])
def update_result():
    """
    Update the result and match events of a match fixture.
    """
    try:
        data = request.json
        match_id = data.get('matchId')
        home_score = data.get('homeScore')
        away_score = data.get('awayScore')
        match_events = data.get('events', [])  # Default to an empty list if not provided

        if not match_id or home_score is None or away_score is None:
            return jsonify({"error": "matchId, homeScore, and awayScore are required"}), 400

        match_ref = db.collection('matches').document(match_id)
        match = match_ref.get()

        if not match.exists:
            return jsonify({"error": "Match not found"}), 404

        update_data = {
            "homeScore": home_score,
            "awayScore": away_score,
            "updatedAt": fs.SERVER_TIMESTAMP
        }

        # Append new match events if provided
        if match_events:
            existing_events = match.to_dict().get("events", [])
            update_data["events"] = existing_events + match_events  # Append new events

        match_ref.update(update_data)

        return jsonify({"message": "Match result and events updated successfully"}), 200

    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error updating match result: %s", e)
        return jsonify({"error": "Internal server error"}), 500
    

@app.route('/schedule/trainings', methods=['GET'])
def get_trainings():
    """
    Retrieve training sessions for a specific month, age group, and division.
    """
    try:
        month = request.args.get('month')  # Format: yyyy-MM
        club_name = request.args.get('clubName')
        age_group = request.args.get('ageGroup')
        division = request.args.get('division')

        if not month or not age_group or not division:
            return jsonify({"error": "Month, age group, and division are required"}), 400

        trainings_ref = db.collection('trainings')
        query = trainings_ref.where('clubName', '==', club_name).where('ageGroup', '==', age_group).where('division', '==', division)

        # Filter by month
        trainings = [
            training.to_dict()
            for training in query.stream()
            if training.to_dict()['date'].startswith(month)
        ]

        return jsonify(trainings), 200

    except Exception as e:
        logging.error("Error fetching trainings: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/schedule/add-training', methods=['POST'])
def add_training():
    """
    Add a new training session to the schedule.
    """
    try:
        data = request.json
        training = {
            "trainingId": str(uuid.uuid4()),
            "ageGroup": data['ageGroup'],
            "division": data['division'],
            "date": data['date'],
            "location": data['location'],
            "notes": data.get('notes', ''),
            "createdBy": data['createdBy']
        }
        db.collection('trainings').document(training['trainingId']).set(training)
        return jsonify({"message": "Training session added successfully"}), 201

    except KeyError as e:
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error adding training session: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/schedule/save-match-data', methods=['POST'])
def save_tactics():
    """
    Save or update tactics for a specific match in the matches collection.
    """
    try:
        data = request.json
        match_id = data.get('matchId')
        formation = data.get('formation')
        strategy_notes = data.get('strategyNotes')
        home_team_lineup = data.get('homeTeamLineup')
        away_team_lineup = data.get('awayTeamLineup')

        if not match_id or not formation:
            return jsonify({"error": "matchId and formation are required"}), 400

        match_ref = db.collection('matches').document(match_id)
        match = match_ref.get()

        if not match.exists:
            return jsonify({"error": "Match not found"}), 404

        # Prepare the update data
        tactics_update = {
            "formation": formation,
            "strategyNotes": strategy_notes if strategy_notes else "",
            "updatedAt": fs.SERVER_TIMESTAMP,
        }

        # Only update lineups if they exist in the request
        if home_team_lineup:
            tactics_update["homeTeamLineup"] = home_team_lineup
        if away_team_lineup:
            tactics_update["awayTeamLineup"] = away_team_lineup

        # Update the match document in the matches collection
        match_ref.update(tactics_update)

        return jsonify({"message": "Tactics saved successfully"}), 200

    except Exception as e:
        logging.error("Error saving tactics: %s", e)
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8083)
    )  # Use PORT environment variable or default to 8083
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
