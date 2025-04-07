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


### 📌 Load Firebase Secret ###
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


### 📌 Firebase Initialization ###
try:
    cred = credentials.Certificate(load_service_account_secret())
    initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase Admin initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Firebase Admin: %s", e)
    raise


### 📌 Helper Function to Get Player Stats Reference ###
def player_stats_ref(club_name, age_group, division, player_email):
    return (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("playerStats")
        .document(player_email)
    )


### 📌 Update Player Stats API ###
@app.route("/stats/update", methods=["POST"])
def update_player_stats():
    """
    Updates player stats when a new event (goal, assist, card) is added to a match.
    """
    try:
        data = request.json
        required_fields = [
            "clubName",
            "ageGroup",
            "division",
            "playerEmail",
            "playerName",
            "eventType",
        ]

        if any(field not in data for field in required_fields):
            return jsonify({"error": "Missing required fields"}), 400

        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        player_email = data["playerEmail"]
        player_name = data["playerName"]
        event_type = data["eventType"]

        ref = player_stats_ref(club_name, age_group, division, player_email)
        player_stats = ref.get().to_dict() or {
            "playerEmail": player_email,
            "playerName": player_name,
            "goals": 0,
            "assists": 0,
            "yellowCards": 0,
            "redCards": 0,
        }

        if event_type == "goal":
            player_stats["goals"] += 1
        elif event_type == "assist":
            player_stats["assists"] += 1
        elif event_type == "yellowCard":
            player_stats["yellowCards"] += 1
        elif event_type == "redCard":
            player_stats["redCards"] += 1

        ref.set(player_stats, merge=True)
        return (
            jsonify(
                {"message": f"Player stats updated for {player_name} ({player_email})"}
            ),
            200,
        )

    except Exception as e:
        logger.exception("Error updating player stats")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### 📌 Get Player Stats API (By Email) ###
@app.route("/stats/get", methods=["GET"])
def get_player_stats():
    """
    Retrieves player statistics for a given player by email.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")
        player_email = request.args.get("playerEmail")

        if not club_name or not age_group or not division or not player_email:
            return jsonify({"error": "Missing required query parameters"}), 400

        ref = player_stats_ref(club_name, age_group, division, player_email)
        stats = ref.get().to_dict()

        if not stats:
            return jsonify({"message": "No stats found for this player."}), 404

        return jsonify(stats), 200

    except Exception as e:
        logger.exception("Error retrieving player stats")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### 📌 Get Player Stats By Name ###
@app.route("/stats/search", methods=["GET"])
def search_players_by_name():
    """
    Searches for players by name and returns their stats.
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")
        player_name = request.args.get("playerName")

        if not club_name or not age_group or not division or not player_name:
            return jsonify({"error": "Missing required query parameters"}), 400

        player_stats_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("playerStats")
        )

        results = []
        for doc in player_stats_ref.stream():
            stats = doc.to_dict()
            if player_name.lower() in stats.get("playerName", "").lower():
                results.append(stats)

        if not results:
            return jsonify({"message": "No players found matching that name."}), 404

        return jsonify(results), 200

    except Exception as e:
        logger.exception("Error searching players by name")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


### 📌 List All Players' Stats ###
@app.route("/stats/list", methods=["GET"])
def list_all_player_stats():
    """
    Lists all player stats and returns top performers (e.g., top scorer, most yellow cards).
    """
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not club_name or not age_group or not division:
            return jsonify({"error": "Missing required query parameters"}), 400

        player_stats_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("playerStats")
        )

        stats_list = [doc.to_dict() for doc in player_stats_ref.stream()]
        if not stats_list:
            return jsonify({"message": "No player stats found."}), 404

        top_scorer = max(stats_list, key=lambda x: x["goals"], default=None)
        most_assists = max(stats_list, key=lambda x: x["assists"], default=None)
        most_yellow_cards = max(
            stats_list, key=lambda x: x["yellowCards"], default=None
        )
        most_red_cards = max(stats_list, key=lambda x: x["redCards"], default=None)

        leaderboard = {
            "topScorer": top_scorer,
            "mostAssists": most_assists,
            "mostYellowCards": most_yellow_cards,
            "mostRedCards": most_red_cards,
        }

        return jsonify({"leaderboard": leaderboard, "allPlayers": stats_list}), 200

    except Exception as e:
        logger.exception("Error listing player stats")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8091))
    logger.info("Starting player-stats service on port %d", port)
    app.run(host="0.0.0.0", port=port)
