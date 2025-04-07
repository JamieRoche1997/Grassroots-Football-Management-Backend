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


def load_secret(secret_name):
    """Load a secret from Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = "grassroots-football-management"
        secret_version = "latest"

        # Build the resource name of the secret version
        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )
        response = client.access_secret_version(request={"name": secret_path})
        secret_value = response.payload.data.decode("UTF-8")

        return secret_value
    except Exception as e:
        logger.error("Error loading secret %s: %s", secret_name, str(e))
        raise RuntimeError(f"Failed to load secret {secret_name}: {str(e)}") from e


# Load Firebase service account
try:
    service_account_info = json.loads(load_secret("firebase-service-account"))
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    logger.debug("Firebase Admin initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Firebase Admin: %s", str(e))
    raise

# Initialise Firestore
db = firestore.client()


### Helpers ###
def notifications_ref(club_name, age_group, division, email):
    return (
        db.collection("clubs")
        .document(club_name)
        .collection("ageGroups")
        .document(age_group)
        .collection("divisions")
        .document(division)
        .collection("notifications")
        .document(email)
    )


# Add FCM Token to Club Collection
@app.route("/add-fcm-token", methods=["POST"])
def add_fcm_token():
    try:
        data = request.get_json()
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        email = data["email"]
        fcm_token = data["fcmToken"]

        ref = notifications_ref(club_name, age_group, division, email)
        ref.set({"fcm_token": fcm_token})

        return jsonify({"message": "FCM token added successfully"}), 200
    except Exception as e:
        logger.error("Failed to add FCM token: %s", str(e))
        return jsonify({"error": "Failed to add FCM token"}), 500


@app.route("/notifications/unread", methods=["POST"])
def get_unread_notifications():
    try:
        data = request.get_json()
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        email = data["email"]

        ref = (
            notifications_ref(club_name, age_group, division, email)
            .collection("messages")
            .where("read", "==", False)
            .order_by("timestamp", direction=fs.Query.DESCENDING)
        )

        docs = ref.stream()
        notifications = [{**doc.to_dict(), "id": doc.id} for doc in docs]

        return jsonify({"notifications": notifications}), 200
    except Exception as e:
        logger.error("Failed to fetch unread notifications: %s", str(e))
        return jsonify({"error": "Failed to fetch notifications"}), 500


@app.route("/notifications/mark-read", methods=["POST"])
def mark_notification_as_read():
    try:
        data = request.get_json()
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        email = data["email"]
        notification_id = data["notificationId"]

        ref = (
            notifications_ref(club_name, age_group, division, email)
            .collection("messages")
            .document(notification_id)
        )

        ref.update({"read": True})

        return jsonify({"message": "Notification marked as read"}), 200
    except Exception as e:
        logger.error("Failed to mark notification as read: %s", str(e))
        return jsonify({"error": "Failed to update notification"}), 500


@app.route("/notifications/all", methods=["POST"])
def get_all_notifications():
    try:
        data = request.get_json()
        club_name = data["clubName"]
        age_group = data["ageGroup"]
        division = data["division"]
        email = data["email"]

        ref = (
            notifications_ref(club_name, age_group, division, email)
            .collection("messages")
            .order_by("timestamp", direction=fs.Query.DESCENDING)
        )

        docs = ref.stream()
        notifications = [{**doc.to_dict(), "id": doc.id} for doc in docs]

        return jsonify({"notifications": notifications}), 200
    except Exception as e:
        logger.error("Failed to fetch all notifications: %s", str(e))
        return jsonify({"error": "Failed to fetch notifications"}), 500


# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8092))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
