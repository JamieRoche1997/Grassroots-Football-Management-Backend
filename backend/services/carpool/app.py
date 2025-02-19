import json
import logging
import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS
from google.cloud import secretmanager

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
        secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
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

        # Ensure matchId is provided
        if "matchId" not in data or not data["matchId"]:
            return jsonify({"error": "matchId is required"}), 400

        ride_ref = db.collection("carpools").document()
        ride_data = {
            "driverName": data["driverName"],
            "seats": data["seats"],
            "location": data["location"],
            "pickup": data["pickup"],
            "time": data["time"],
            "matchId": data["matchId"],  # ✅ Store matchId
            "matchDetails": data["matchDetails"],  # ✅ Store match details
        }

        ride_ref.set(ride_data)
        return jsonify({"message": "Ride added successfully", "ride_id": ride_ref.id}), 201

    except Exception as e:
        logger.error("Error offering ride: %s", str(e))
        return jsonify({"error": str(e)}), 500


# 🚙 Get Available Rides
@app.route("/carpool/rides", methods=["GET"])
def get_rides():
    try:
        rides = db.collection("carpools").stream()
        ride_list = [{**ride.to_dict(), "id": ride.id} for ride in rides]
        return jsonify(ride_list), 200
    except Exception as e:
        logger.error("Error fetching rides: %s", str(e))
        return jsonify({"error": str(e)}), 500


# 📩 Request a Ride
@app.route("/carpool/request", methods=["POST"])
def request_ride():
    try:
        data = request.json
        request_ref = db.collection("ride_requests").document()
        request_data = {
            "userName": data["userName"],
            "ride_id": data["ride_id"],
            "status": "pending",
        }
        request_ref.set(request_data)
        return jsonify({"message": "Ride request submitted"}), 201
    except Exception as e:
        logger.error("Error requesting ride: %s", str(e))
        return jsonify({"error": str(e)}), 500


# ❌ Cancel a Ride
@app.route("/carpool/cancel/<ride_id>", methods=["DELETE"])
def cancel_ride(ride_id):
    try:
        db.collection("carpools").document(ride_id).delete()
        return jsonify({"message": "Ride cancelled successfully"}), 200
    except Exception as e:
        logger.error("Error cancelling ride: %s", str(e))
        return jsonify({"error": str(e)}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8086))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
