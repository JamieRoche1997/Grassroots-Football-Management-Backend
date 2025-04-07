import json
import logging
import os
import uuid
from flask import Flask, request, jsonify
from firebase_admin import credentials, initialize_app, firestore, messaging
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


### CREATE FIXTURE ###
# CREATE FIXTURE
@app.route("/schedule/fixture", methods=["POST"])
def add_fixture():
    try:
        data = request.json
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        match_id = str(uuid.uuid4())
        home_team = data["homeTeam"]
        away_team = data["awayTeam"]
        date = data["date"]
        created_by = data["createdBy"]

        formatted_date, formatted_time = date.split("T")

        fixture = {
            "matchId": match_id,
            "homeTeam": home_team,
            "awayTeam": away_team,
            "date": date,
            "createdBy": created_by,
        }
        (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("fixtures")
            .document(match_id)
            .set(fixture)
        )

        tokens_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("notifications")
        )

        notifications_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("notifications")
        )

        for doc in tokens_ref.stream():
            token_data = doc.to_dict()
            email = doc.id  # use document ID as the email identifier
            fcm_token = token_data.get("fcm_token")

            if not fcm_token:
                continue

            # Send FCM notification
            message = messaging.Message(
                token=fcm_token,
                notification=messaging.Notification(
                    title="📅 New Fixture Scheduled",
                    body=f"Date: {formatted_date}\nTime: {formatted_time}\n{home_team} vs {away_team}",
                ),
            )
            messaging.send(message)

            # Save to Firestore
            notifications_ref.document(email).collection("messages").add(
                {
                    "type": "training",
                    "title": "📅 New Fixture Scheduled",
                    "body": f"Date: {formatted_date}, Time: {formatted_time}, {home_team} vs {away_team}",
                    "timestamp": fs.SERVER_TIMESTAMP,
                    "read": False,
                    "relatedId": match_id,
                }
            )

        return (
            jsonify({"message": "Training session added and notifications sent"}),
            201,
        )

    except Exception as e:
        logging.error("Error adding training session: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### UPDATE FIXTURE ###
# UPDATE FIXTURE
@app.route("/schedule/fixture", methods=["PUT"])
def update_fixture():
    try:
        data = request.json
        match_id = data["matchId"]

        fixture_update = {
            k: v for k, v in data.items() if k in ["homeTeam", "awayTeam", "date"]
        }
        fixture_update["updatedAt"] = fs.SERVER_TIMESTAMP

        (
            db.collection("clubs")
            .document(data["clubName"])
            .collection("ageGroups")
            .document(data["ageGroup"])
            .collection("divisions")
            .document(data["division"])
            .collection("fixtures")
            .document(match_id)
            .update(fixture_update)
        )

        return jsonify({"message": "Fixture updated successfully"}), 200

    except Exception as e:
        logging.error("Error updating fixture: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### DELETE FIXTURE ###
# DELETE FIXTURE
@app.route("/schedule/fixture", methods=["DELETE"])
def delete_fixture():
    try:
        match_id = request.args.get("matchId")
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("fixtures")
            .document(match_id)
            .delete()
        )

        return jsonify({"message": "Fixture deleted successfully"}), 200

    except Exception as e:
        logging.error("Error deleting fixture: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### GET FIXTURES ###
# GET FIXTURE BY MATCH ID
@app.route("/schedule/fixture/<matchId>", methods=["GET"])
def get_fixture_by_id(matchId):
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        fixture_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("fixtures")
            .document(matchId)
        )

        fixture = fixture_ref.get()

        if not fixture.exists:
            return jsonify({"error": "Fixture not found"}), 404

        return jsonify(fixture.to_dict()), 200

    except Exception as e:
        logging.error("Error fetching fixture by ID: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# GET ALL FIXTURES
@app.route("/schedule/fixtures", methods=["GET"])
def get_all_fixtures():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        fixtures_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("fixtures")
        )

        fixtures = [fixture.to_dict() for fixture in fixtures_ref.stream()]
        return jsonify(fixtures), 200

    except Exception as e:
        logging.error("Error fetching all fixtures: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# GET FIXTURES BY MONTH
@app.route("/schedule/fixture", methods=["GET"])
def get_fixtures():
    try:
        month = request.args.get("month")
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not month or not age_group or not division:
            return (
                jsonify({"error": "Month, age group, and division are required"}),
                400,
            )

        fixtures_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("fixtures")
        )

        fixtures = [
            fixture.to_dict()
            for fixture in fixtures_ref.stream()
            if fixture.to_dict()["date"].startswith(month)
        ]
        return jsonify(fixtures), 200

    except Exception as e:
        logging.error("Error fetching fixtures: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/schedule/fixture/availability", methods=["POST"])
def update_availability():
    data = request.get_json()
    club_name = data["clubName"]
    age_group = data["ageGroup"]
    division = data["division"]
    email = data["email"]
    available = data["available"]
    match_id = data["matchId"]

    doc_ref = (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("fixtures")
        .document(match_id)
        .collection("availability")
        .document(email)
    )

    doc_ref.set({"available": available, "timestamp": fs.SERVER_TIMESTAMP})

    return jsonify({"message": "Availability updated"}), 200


@app.route("/schedule/fixture/availability", methods=["GET"])
def get_availability():
    club_name = request.args.get("clubName")
    age_group = request.args.get("ageGroup")
    division = request.args.get("division")
    match_id = request.args.get("matchId")

    availability_ref = (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("fixtures")
        .document(match_id)
        .collection("availability")
    )

    docs = availability_ref.stream()
    availability = [{**doc.to_dict(), "email": doc.id} for doc in docs]

    return jsonify({"availability": availability}), 200


### CREATE TRAINING ###
# CREATE TRAINING
@app.route("/schedule/training", methods=["POST"])
def add_training():
    try:
        data = request.json
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        training_id = str(uuid.uuid4())
        date = data["date"]
        location = data["location"]
        notes = data.get("notes", "")
        created_by = data["createdBy"]

        formatted_date, formatted_time = date.split("T")

        training = {
            "trainingId": training_id,
            "date": date,
            "location": location,
            "notes": notes,
            "createdBy": created_by,
        }
        (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("trainings")
            .document(training_id)
            .set(training)
        )

        tokens_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("notifications")
        )

        notifications_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("notifications")
        )

        for doc in tokens_ref.stream():
            token_data = doc.to_dict()
            email = doc.id  # use document ID as the email identifier
            fcm_token = token_data.get("fcm_token")

            if not fcm_token:
                continue

            # Send FCM notification
            message = messaging.Message(
                token=fcm_token,
                notification=messaging.Notification(
                    title="📅 New Training Scheduled",
                    body=f"Date: {formatted_date}\nTime: {formatted_time}\nLocation: {location}",
                ),
            )
            messaging.send(message)

            # Save to Firestore
            notifications_ref.document(email).collection("messages").add(
                {
                    "type": "training",
                    "title": "📅 New Training Scheduled",
                    "body": f"Date: {formatted_date}, Time: {formatted_time}, Location: {location}",
                    "timestamp": fs.SERVER_TIMESTAMP,
                    "read": False,
                    "relatedId": training_id,
                }
            )

        return (
            jsonify({"message": "Training session added and notifications sent"}),
            201,
        )

    except Exception as e:
        logging.error("Error adding training session: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### UPDATE TRAINING ###
# UPDATE TRAINING
@app.route("/schedule/training", methods=["PUT"])
def update_training():
    try:
        data = request.json
        training_id = data["trainingId"]

        training_update = {
            k: v for k, v in data.items() if k in ["date", "location", "notes"]
        }
        training_update["updatedAt"] = fs.SERVER_TIMESTAMP

        (
            db.collection("clubs")
            .document(data["clubName"])
            .collection("ageGroups")
            .document(data["ageGroup"])
            .collection("divisions")
            .document(data["division"])
            .collection("trainings")
            .document(training_id)
            .update(training_update)
        )

        return jsonify({"message": "Training updated successfully"}), 200

    except Exception as e:
        logging.error("Error updating training: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### DELETE TRAINING ###
# DELETE TRAINING
@app.route("/schedule/training", methods=["DELETE"])
def delete_training():
    try:
        training_id = request.args.get("trainingId")
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("trainings")
            .document(training_id)
            .delete()
        )

        return jsonify({"message": "Training deleted successfully"}), 200

    except Exception as e:
        logging.error("Error deleting training: %s", e)
        return jsonify({"error": "Internal server error"}), 500


### GET TRAINING ###
# GET TRAINING BY TRAINING ID
@app.route("/schedule/training/<trainingId>", methods=["GET"])
def get_training_by_id(trainingId):
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        training_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("trainings")
            .document(trainingId)
        )

        training = training_ref.get()

        if not training.exists:
            return jsonify({"error": "Training not found"}), 404

        return jsonify(training.to_dict()), 200

    except Exception as e:
        logging.error("Error fetching training by ID: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# GET ALL TRAININGS
@app.route("/schedule/trainings", methods=["GET"])
def get_all_trainings():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        trainings_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("trainings")
        )

        trainings = [training.to_dict() for training in trainings_ref.stream()]
        return jsonify(trainings), 200

    except Exception as e:
        logging.error("Error fetching all trainings: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# GET TRAINING BY MONTH
@app.route("/schedule/training", methods=["GET"])
def get_trainings():
    try:
        month = request.args.get("month")
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not month or not age_group or not division:
            return (
                jsonify({"error": "Month, age group, and division are required"}),
                400,
            )

        trainings_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("trainings")
        )

        trainings = [
            training.to_dict()
            for training in trainings_ref.stream()
            if training.to_dict()["date"].startswith(month)
        ]
        return jsonify(trainings), 200

    except Exception as e:
        logging.error("Error fetching trainings: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/schedule/training/availability", methods=["POST"])
def update_training_availability():
    data = request.get_json()
    club_name = data["clubName"]
    age_group = data["ageGroup"]
    division = data["division"]
    email = data["email"]
    available = data["available"]
    training_id = data["trainingId"]

    doc_ref = (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("trainings")
        .document(training_id)
        .collection("availability")
        .document(email)
    )

    doc_ref.set({"available": available, "timestamp": fs.SERVER_TIMESTAMP})

    return jsonify({"message": "Availability updated"}), 200


@app.route("/schedule/training/availability", methods=["GET"])
def get_training_availability():
    club_name = request.args.get("clubName")
    age_group = request.args.get("ageGroup")
    division = request.args.get("division")
    training_id = request.args.get("trainingId")

    availability_ref = (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("trainings")
        .document(training_id)
        .collection("availability")
    )

    docs = availability_ref.stream()
    availability = [{**doc.to_dict(), "email": doc.id} for doc in docs]

    return jsonify({"availability": availability}), 200


if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 8083)
    )  # Use PORT environment variable or default to 8083
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
