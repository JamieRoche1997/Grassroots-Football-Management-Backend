import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import firestore as fs, secretmanager

app = Flask(__name__)
CORS(app)

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
        logger.error("Error loading service account secret: %s", e)
        raise


try:
    cred = credentials.Certificate(load_service_account_secret())
    initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase Admin initialised successfully")
except Exception as e:
    logger.error("Failed to initialise Firebase Admin: %s", e)
    raise


### Helpers ###
def fixture_ref(club_name, age_group, division, match_id):
    return (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("fixtures")
        .document(match_id)
    )


### Lineups ###
@app.route("/fixture/lineups", methods=["POST", "PATCH", "DELETE", "GET"])
def manage_lineups():
    try:
        if request.method in ["POST", "PATCH", "DELETE"]:
            data = request.json
        else:
            data = request.args
        ref = fixture_ref(
            data["clubName"], data["ageGroup"], data["division"], data["matchId"]
        )

        if request.method == "POST":
            ref.collection("lineups").document("home").set(
                {"lineup": data.get("homeTeamLineup", {})}
            )
            ref.collection("lineups").document("away").set(
                {"lineup": data.get("awayTeamLineup", {})}
            )
            return jsonify({"message": "Lineups saved successfully"}), 201

        elif request.method == "PATCH":
            home_update = data.get("homeTeamLineup")
            away_update = data.get("awayTeamLineup")
            if home_update:
                ref.collection("lineups").document("home").update(
                    {"lineup": home_update}
                )
            if away_update:
                ref.collection("lineups").document("away").update(
                    {"lineup": away_update}
                )
            return jsonify({"message": "Lineups updated successfully"}), 200

        elif request.method == "DELETE":
            ref.collection("lineups").document("home").delete()
            ref.collection("lineups").document("away").delete()
            return jsonify({"message": "Lineups deleted successfully"}), 200

        elif request.method == "GET":
            matchId = request.args.get("matchId")
            clubName = request.args.get("clubName")
            ageGroup = request.args.get("ageGroup")
            division = request.args.get("division")

            ref = fixture_ref(clubName, ageGroup, division, matchId)
            home_lineup = (
                ref.collection("lineups").document("home").get().to_dict() or {}
            )
            away_lineup = (
                ref.collection("lineups").document("away").get().to_dict() or {}
            )
            return (
                jsonify(
                    {
                        "homeTeamLineup": home_lineup.get("lineup", {}),
                        "awayTeamLineup": away_lineup.get("lineup", {}),
                    }
                ),
                200,
            )

    except Exception as e:
        logger.exception("Error managing lineups")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### Events ###
@app.route("/fixture/events", methods=["POST", "PATCH", "DELETE", "GET"])
def manage_events():
    try:
        if request.method in ["POST", "PATCH", "DELETE"]:
            data = request.json
        else:
            data = request.args
        ref = fixture_ref(
            data["clubName"], data["ageGroup"], data["division"], data["matchId"]
        )

        if request.method == "POST":
            event_ref = ref.collection("events").document()
            event_ref.set(data["event"])
            return (
                jsonify(
                    {"message": "Event added successfully", "eventId": event_ref.id}
                ),
                201,
            )

        elif request.method == "PATCH":
            event_id = data["eventId"]
            ref.collection("events").document(event_id).update(data["event"])
            return jsonify({"message": "Event updated successfully"}), 200

        elif request.method == "DELETE":
            event_id = data["eventId"]
            ref.collection("events").document(event_id).delete()
            return jsonify({"message": "Event deleted successfully"}), 200

        elif request.method == "GET":
            matchId = request.args.get("matchId")
            clubName = request.args.get("clubName")
            ageGroup = request.args.get("ageGroup")
            division = request.args.get("division")

            ref = fixture_ref(clubName, ageGroup, division, matchId)
            events = [doc.to_dict() for doc in ref.collection("events").stream()]
            return jsonify(events), 200

    except Exception as e:
        logger.exception("Error managing events")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### Results ###
@app.route("/fixture/results", methods=["POST", "PATCH", "DELETE", "GET"])
def manage_results():
    try:
        if request.method in ["POST", "PATCH", "DELETE"]:
            data = request.json
        else:
            data = request.args
        ref = fixture_ref(
            data["clubName"], data["ageGroup"], data["division"], data["matchId"]
        )
        result_ref = ref.collection("results").document("final")

        if request.method == "POST":
            result_ref.set(
                {
                    "homeScore": data["homeScore"],
                    "awayScore": data["awayScore"],
                    "updatedAt": fs.SERVER_TIMESTAMP,
                }
            )
            return jsonify({"message": "Result saved successfully"}), 201

        elif request.method == "PATCH":
            result_ref.update(
                {
                    "homeScore": data.get("homeScore"),
                    "awayScore": data.get("awayScore"),
                    "updatedAt": fs.SERVER_TIMESTAMP,
                }
            )
            return jsonify({"message": "Result updated successfully"}), 200

        elif request.method == "DELETE":
            result_ref.delete()
            return jsonify({"message": "Result deleted successfully"}), 200

        elif request.method == "GET":
            matchId = request.args.get("matchId")
            clubName = request.args.get("clubName")
            ageGroup = request.args.get("ageGroup")
            division = request.args.get("division")

            ref = fixture_ref(clubName, ageGroup, division, matchId)
            result_ref = ref.collection("results").document("final")
            result = result_ref.get()
            if not result.exists:
                return jsonify({"error": "Result not found"}), 404
            return jsonify(result.to_dict()), 200

    except Exception as e:
        logger.exception("Error managing results")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### Player Ratings ###
@app.route("/fixture/player", methods=["POST", "GET", "PATCH", "DELETE"])
def manage_player_ratings():
    try:
        if request.method in ["POST", "PATCH", "DELETE"]:
            data = request.json
        else:
            data = request.args

        required_fields = ["clubName", "ageGroup", "division", "matchId"]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return (
                jsonify(
                    {"error": f"Missing required fields: {', '.join(missing_fields)}"}
                ),
                400,
            )

        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        match_id = data["matchId"]

        if request.method == "POST":
            player_email = data["playerEmail"]

            rating_ref = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("fixtures")
                .document(match_id)
                .collection("playerRatings")
                .document(player_email)
            )

            rating_data = {k: v for k, v in data.items() if k not in required_fields}
            rating_data.update(
                {"playerEmail": player_email, "createdAt": fs.SERVER_TIMESTAMP}
            )
            rating_ref.set(rating_data)
            return jsonify({"message": "Player rating submitted successfully"}), 201

        elif request.method == "GET":
            matchId = request.args.get("matchId")
            clubName = request.args.get("clubName")
            ageGroup = request.args.get("ageGroup")
            division = request.args.get("division")

            ratings = []
            ratings_ref = (
                db.collection("clubs")
                .document(clubName)
                .collection("ageGroups")
                .document(ageGroup)
                .collection("divisions")
                .document(division)
                .collection("fixtures")
                .document(matchId)
                .collection("playerRatings")
            )
            for doc in ratings_ref.stream():
                ratings.append(doc.to_dict())
            return jsonify(ratings), 200

        elif request.method == "PATCH":
            player_email = data["playerEmail"]

            rating_ref = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("fixtures")
                .document(match_id)
                .collection("playerRatings")
                .document(player_email)
            )

            update_data = {k: v for k, v in data.items() if k not in required_fields}
            if not update_data:
                return jsonify({"error": "No fields provided to update"}), 400

            update_data["updatedAt"] = fs.SERVER_TIMESTAMP
            rating_ref.update(update_data)
            return jsonify({"message": "Player rating updated successfully"}), 200

        elif request.method == "DELETE":
            player_email = data["playerEmail"]

            rating_ref = (
                db.collection("clubs")
                .document(club_name)
                .collection("ageGroups")
                .document(age_group)
                .collection("divisions")
                .document(division)
                .collection("fixtures")
                .document(match_id)
                .collection("playerRatings")
                .document(player_email)
            )

            rating_ref.delete()
            return jsonify({"message": "Player rating deleted successfully"}), 200

    except Exception as e:
        logger.exception("Error managing player ratings")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8085))
    logger.info("Starting match-management on port %d", port)
    app.run(host="0.0.0.0", port=port)
