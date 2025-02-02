from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests

# Initialize Firebase Admin SDK
cred = credentials.Certificate('/app/serviceKey.json')  # Replace with your service account key path
initialize_app(cred)

# Initialize Firestore
db = firestore.client()

@app.route('/user/update', methods=['POST'])
def update_user_profile():
    try:
        data = request.json
        
        # Validate email
        if 'email' not in data or not data['email']:
            return jsonify({'error': 'Email is required'}), 400
        
        email = data['email']
        user_ref = db.collection('users').document(email)

        # Dynamically update Firestore with provided fields
        update_data = {key: value for key, value in data.items() if key != 'email'}

        if not update_data:
            return jsonify({'error': 'No fields provided for update'}), 400

        user_ref.update(update_data)

        return jsonify({'message': 'User profile updated successfully'}), 200

    except KeyError as e:
        return jsonify({'error': 'Missing key: ' + str(e)}), 400
    except ValueError as e:
        return jsonify({'error': 'Invalid input: ' + str(e)}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
