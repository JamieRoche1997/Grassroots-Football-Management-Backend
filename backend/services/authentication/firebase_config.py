import firebase_admin
from firebase_admin import credentials, auth, firestore

# Load the service account key
cred = credentials.Certificate("/app/serviceKey.json")

# Initialize Firebase app
firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()
