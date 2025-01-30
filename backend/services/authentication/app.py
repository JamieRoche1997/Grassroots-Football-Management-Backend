from flask import Flask, request, jsonify
from firebase_admin import auth, firestore
import firebase_config

app = Flask(__name__)
db = firebase_config.db  # Firestore client


def create_firestore_user(user_data):
    """Store user details in Firestore under 'users' collection."""
    user_ref = db.collection('users').document(user_data['email'])
    user_ref.set({
        'name': user_data['name'],
        'email': user_data['email'],
        'role': user_data['role'],
        'phone': user_data.get('phone', ''),
        'dob': user_data.get('dob', ''),
        'club': user_data.get('club', ''),
    })


@app.route('/register', methods=['POST'])
def register():
    try:
        # Parse request JSON
        data = request.json
        email = data['email']
        password = data['password']
        name = data['name']
        role = data.get('role', 'player')

        # Create user in Firebase Authentication
        user = auth.create_user(
            email=email,
            password=password,
            display_name=name,
        )

        # Store user information in Firestore
        user_data = {
            'name': name,
            'email': email,
            'role': role,
            'phone': data.get('phone'),
            'dob': data.get('dob'),
            'club': data.get('club', ''),
        }
        create_firestore_user(user_data)

        # Return success response
        return jsonify({
            'message': 'User registered successfully',
            'firebase_uid': user.uid,
            'email': email,
            'name': name,
            'role': role,
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
