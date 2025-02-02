from flask import Flask, request, jsonify
from firebase_admin import auth, credentials, firestore, initialize_app
from firebase_admin.auth import InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize Firebase Admin SDK
cred = credentials.Certificate('/app/serviceKey.json')  # Replace with your service account key path
initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# Create Firestore user
def create_firestore_user(user_data):
    try:
        user_ref = db.collection('users').document(user_data['email'])
        user_ref.set({
            'uid': user_data['uid'],
            'name': user_data['name'],
            'email': user_data['email'],
            'role': user_data['role'],
        })
    except Exception as e:
        raise RuntimeError(f"Failed to create Firestore user: {str(e)}") from e

# Sign Up
@app.route('/signup', methods=['POST'])
def register():
    try:
        data = request.json
        email = data['email']
        password = data['password']
        name = data['name']
        role = data.get('role', 'player')  # Default role is 'player'

        # Create user in Firebase Authentication
        user = auth.create_user(
            email=email,
            password=password,
            display_name=name,
        )

        # Store user information in Firestore
        user_data = {
            'uid': user.uid,
            'name': name,
            'email': email,
            'role': role,
        }
        create_firestore_user(user_data)

        return jsonify({
            'message': 'User registered successfully',
            'firebase_uid': user.uid,
            'email': email,
            'name': name,
            'role': role,
        }), 201

    except auth.EmailAlreadyExistsError:
        return jsonify({'error': 'Email already exists'}), 400
    except KeyError as e:
        return jsonify({'error': f'Missing key: {str(e)}'}), 400
    except TypeError as e:
        return jsonify({'error': f'Type error: {str(e)}'}), 400
    except ValueError as e:
        return jsonify({'error': f'Value error: {str(e)}'}), 400

# Sign In
@app.route('/signin', methods=['POST'])
def sign_in():
    try:
        data = request.json
        id_token = data['idToken']

        # Verify the ID token using Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token)
        user = auth.get_user(decoded_token['uid'])

        return jsonify({
            'message': 'User signed in successfully',
            'firebase_uid': user.uid,
            'email': user.email,
        }), 200

    except (InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError):
        return jsonify({'error': 'Invalid or expired ID token'}), 401
    except KeyError as e:
        return jsonify({'error': f'Missing key: {str(e)}'}), 400
    except ValueError as e:
        return jsonify({'error': f'Value error: {str(e)}'}), 400

# Run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)