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
    """Load the Firebase service account credentials from Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = "grassroots-football-management"
        secret_name = "firebase-service-account"
        secret_version = "latest"

        # Build the resource name of the secret version
        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )
        response = client.access_secret_version(request={"name": secret_path})
        service_account_info = response.payload.data.decode("UTF-8")

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


# 🚘 Offer a Ride (Updated)
@app.route("/carpool/offer", methods=["POST"])
def offer_ride():
    try:
        data = request.json
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")
        match_id = data.get("matchId")

        # Ensure matchId is provided
        if "matchId" not in data or not data["matchId"]:
            return jsonify({"error": "matchId is required"}), 400

        ride_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("carpools")
            .document()
        )

        ride_data = {
            "id": ride_ref.id,
            "driverName": data["driverName"],
            "driverEmail": data["driverEmail"],
            "seats": data["seats"],
            "location": data["location"],
            "pickup": data["pickup"],
            "time": data["time"],
            "matchId": match_id,  # ✅ Store matchId
            "matchDetails": data["matchDetails"],  # ✅ Store match details
        }

        ride_ref.set(ride_data)
        return (
            jsonify({"message": "Ride added successfully", "ride_id": ride_ref.id}),
            201,
        )

    except Exception as e:
        logger.error("Error offering ride: %s", str(e))
        return jsonify({"error": str(e)}), 500


# 🚙 Get Available Rides
@app.route("/carpool/rides", methods=["GET"])
def get_rides():
    try:
        club_name = request.args.get("clubName")
        age_group = request.args.get("ageGroup")
        division = request.args.get("division")

        if not all([club_name, age_group, division]):
            return jsonify({"error": "Missing required query parameters"}), 400

        rides = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("carpools")
            .stream()
        )

        ride_list = [{**ride.to_dict(), "id": ride.id} for ride in rides]

        return jsonify(ride_list), 200

    except Exception as e:
        logger.error("Error fetching rides: %s", str(e))
        return jsonify({"error": "Internal server error"}), 500


# 📩 Request a Ride
@app.route("/carpool/request", methods=["POST"])
def request_ride():
    try:
        data = request.json
        user_name = data.get("userName")
        ride_id = data.get("ride_id")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not user_name or not ride_id:
            return jsonify({"error": "userName and ride_id are required"}), 400

        ride_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("carpools")
            .document(ride_id)
        )
        ride = ride_ref.get()

        if not ride.exists:
            return jsonify({"error": "Ride not found"}), 404

        ride_data = ride.to_dict()

        # Ensure there are available seats
        if ride_data["seats"] <= 0:
            return jsonify({"error": "No available seats"}), 400

        # Update ride document: Reduce seats & add user to `passengers`
        ride_ref.update(
            {"seats": ride_data["seats"] - 1, "passengers": fs.ArrayUnion([user_name])}
        )

        return (
            jsonify(
                {"message": "Ride confirmed", "ride_id": ride_id, "user": user_name}
            ),
            200,
        )

    except Exception as e:
        logger.error("Error confirming ride request: %s", str(e))
        return jsonify({"error": str(e)}), 500


# ❌ Cancel a Ride
@app.route("/carpool/cancel", methods=["POST"])
def cancel_ride():
    try:
        data = request.json
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")
        ride_id = data.get("rideId")  # ✅ Get ride ID from request body

        if not ride_id:
            return jsonify({"error": "Missing rideId in request body"}), 400

        logger.info(
            "Received request to cancel ride: %s", ride_id
        )  # ✅ Log received ride ID

        ride_ref = (
            db.collection("clubs")
            .document(club_name)
            .collection("ageGroups")
            .document(age_group)
            .collection("divisions")
            .document(division)
            .collection("carpools")
            .document(ride_id)
        )
        ride = ride_ref.get()

        if not ride.exists:
            return jsonify({"error": "Ride not found"}), 404

        ride_ref.delete()
        return jsonify({"message": "Ride cancelled successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8086))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
