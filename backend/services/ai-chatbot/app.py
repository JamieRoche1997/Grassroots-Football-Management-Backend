import json
import logging
import os
import requests
from openai import OpenAI
from flask import Flask, request, jsonify
from flask_cors import CORS
from firebase_admin import credentials, firestore, initialize_app, auth
from google.cloud import secretmanager

# --------------------------------------------------------------------------------
# 1) Flask App Setup
# --------------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------
# 2) Utility to load secrets from Google Secret Manager
# --------------------------------------------------------------------------------
def load_secret(secret_name):
    """
    Retrieve secrets (Firebase service account, OpenAI API key, etc.) from
    Google Secret Manager.
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = "grassroots-football-management"
        secret_version = "latest"

        secret_path = (
            f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        )
        response = client.access_secret_version(request={"name": secret_path})
        secret_value = response.payload.data.decode("UTF-8")
        return secret_value
    except Exception as e:
        logger.error("Error loading secret %s: %s", secret_name, str(e))
        raise RuntimeError(f"Failed to load secret {secret_name}: {str(e)}") from e


# --------------------------------------------------------------------------------
# 3) Firebase Initialization
# --------------------------------------------------------------------------------
try:
    service_account_info = json.loads(load_secret("firebase-service-account"))
    cred = credentials.Certificate(service_account_info)
    initialize_app(cred)
    db = firestore.client()
    logger.debug("Firebase Admin initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Firebase Admin: %s", str(e))
    raise

# --------------------------------------------------------------------------------
# 4) OpenAI Initialization
# --------------------------------------------------------------------------------
try:
    openai_api_key = load_secret("openai-api-key")
    logger.debug("OpenAI API key loaded successfully")
except Exception as e:
    logger.error("Failed to load OpenAI API key: %s", str(e))
    raise

openai_client = OpenAI(api_key=openai_api_key)

# --------------------------------------------------------------------------------
# 5) Allowed function(s) for GPT
#     We'll define just one function: "getUserClubInfo".
# --------------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getUserClubInfo",
            "description": "Retrieve the club info of a user by email (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "User email"}
                },
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchClubs",
            "description": "Search for clubs with optional filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "county": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getPlayers",
            "description": "Retrieve players for a club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getScheduledMatches",
            "description": "Retrieve scheduled matches for a month, club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["month", "clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getScheduledTrainings",
            "description": "Retrieve scheduled training sessions for a month, club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["month", "clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getPlayerRatings",
            "description": "Retrieve player ratings for a club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getMatchRatings",
            "description": "Retrieve match ratings for a club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getRides",
            "description": "Retrieve all available carpool rides.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listProducts",
            "description": "Retrieve products for a team in a club.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listTransactions",
            "description": "Retrieve transaction history for a user.",
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        },
    },
]


# --------------------------------------------------------------------------------
# 6) The system prompt
# --------------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a helpful AI assistant for Grassroots Football Management.

You are assisting user {user_email}. Their club is {club_name}, age group is {age_group}, and division is {division}.

You can ONLY retrieve data via GET requests from the microservices.
Never propose or perform POST, PUT, PATCH, or DELETE.
If the user’s request requires an update, politely refuse.

The user's email is {user_email}, ID token is {id_token}, month is {current_month}.

Begin:
"""


# --------------------------------------------------------------------------------
# 7) The /query-ai route using function calling
# --------------------------------------------------------------------------------
@app.route("/query-ai", methods=["POST"])
def query_ai():
    """
    Receives JSON:
    {
      "message": "...",
      "token": "...",
      "email": "..."
    }

    Verifies the user, calls OpenAI ChatCompletion with function calling.
    If GPT returns a tool_calls to getUserClubInfo, we call the API gateway
    /user/club-info?email=..., then return the final answer to the user.
    """
    try:
        data = request.json
        user_message = data.get("message")
        id_token = data.get("token")
        user_email = data.get("email")
        month = data.get("month")
        club_name = data.get("clubName")
        age_group = data.get("ageGroup")
        division = data.get("division")

        if not user_message or not id_token or not user_email:
            return jsonify({"error": "Missing required fields"}), 400

        # Verify Firebase ID token
        try:
            decoded = auth.verify_id_token(id_token)
            if decoded.get("email") != user_email:
                return jsonify({"error": "Email mismatch"}), 403
        except Exception as e:
            logger.error("Invalid Firebase token: %s", str(e))
            return jsonify({"error": "Invalid token"}), 401

        # Build system + user messages
        system_prompt = SYSTEM_PROMPT.format(
            user_email=user_email,
            club_name=club_name,
            age_group=age_group,
            division=division,
            current_month=month,
            id_token=id_token,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Call GPT with function definitions
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        msg = response.choices[0].message

        # Check if GPT returned a function call
        if msg.tool_calls:
            replies = []  # Store multiple replies if multiple tool calls exist

            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except Exception as ex:
                    logger.error("Error parsing function call arguments: %s", str(ex))
                    fn_args = {}

                reply = None

                if fn_name == "getUserClubInfo":
                    reply = call_external_service(
                        "getUserClubInfo",
                        "/user/club-info",
                        fn_args,
                        id_token,
                        user_message,
                    )

                elif fn_name == "searchClubs":
                    reply = call_external_service(
                        "searchClubs",
                        "/club/search",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getPlayers":
                    reply = call_external_service(
                        "getPlayers",
                        "/club/players",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getScheduledMatches":
                    reply = call_external_service(
                        "getScheduledMatches",
                        "/schedule/matches",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getScheduledTrainings":
                    reply = call_external_service(
                        "getScheduledTrainings",
                        "/schedule/trainings",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getPlayerRatings":
                    reply = call_external_service(
                        "getPlayerRatings",
                        "/player/get-ratings",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getMatchRatings":
                    reply = call_external_service(
                        "getMatchRatings",
                        "/match/get-ratings",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getRides":
                    reply = call_external_service(
                        "getRides",
                        "/carpool/rides",
                        {},
                        id_token,
                        user_message,
                    )
                elif fn_name == "listProducts":
                    reply = call_external_service(
                        "listProducts",
                        "/products/list",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "listTransactions":
                    reply = call_external_service(
                        "listTransactions",
                        "/transactions/list",
                        fn_args,
                        id_token,
                        user_message,
                    )
                else:
                    reply = "Unknown function call received."

                if reply:
                    replies.append(reply)

            return jsonify({"reply": "\n".join(replies)}), 200

        else:
            # GPT gave a direct text response with no function call
            final_text = msg.content
            return jsonify({"reply": final_text}), 200

    except Exception as e:
        logger.exception("Error in /query-ai")
        return jsonify({"error": str(e)}), 500


def call_external_service(fn_name, base_url, params, id_token, original_user_message):
    response = requests.get(
        "https://grassroots-gateway-2au66zeb.nw.gateway.dev" + base_url,
        headers={"Authorization": f"Bearer {id_token}"},
        params=params,
        timeout=20,
    )
    if response.status_code == 200:
        data = response.json()

        followup_messages = [
            {
                "role": "system",
                "content": f"""
You have retrieved data from the {fn_name} endpoint.

Your job is to convert this into a clear, helpful message for the user, who is a grassroots football manager.

Use concise bullet points. Never show email addresses or sensitive data. Use plain text, do not use HTML or markdown language in the response.
Avoid raw JSON-like responses unless absolutely necessary. 
Explain the significance of the data where relevant.
""",
            },
            {"role": "user", "content": f"The user asked: {original_user_message}. Here is the data you retrieved: {json.dumps(data)}"},
        ]

        second_response = openai_client.chat.completions.create(
            model="gpt-4o", messages=followup_messages, temperature=0.4
        )
        return second_response.choices[0].message.content
    else:
        return f"{fn_name} failed with status {response.status_code}: {response.text}"


# --------------------------------------------------------------------------------
# 8) Run the Flask app
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8088))
    logger.info("Starting app on port %d", port)
    app.run(host="0.0.0.0", port=port)
