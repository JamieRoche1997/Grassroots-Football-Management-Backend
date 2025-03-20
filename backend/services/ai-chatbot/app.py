import json
import logging
from datetime import datetime
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
# Define TOOLS array using only GET endpoints from openapi.yaml
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getPlayers",
            "description": "Retrieve players for a specific club, age group, and division.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "name": {"type": "string"},
                        "position": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
                "description": "List of players with their details.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listTeamMembers",
            "description": "Fetches all players using query params (clubName, ageGroup, division)",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "position": {"type": "string"},
                        "role": {"type": "string"},
                        "joinedAt": {"type": "string"},
                        "updatedAt": {"type": "string"},
                    },
                },
                "description": "List of players with their details.",
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
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "clubName": {"type": "string"},
                        "county": {"type": "string"},
                        "ageGroups": {"type": "array", "items": {"type": "string"}},
                        "divisions": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "description": "List of clubs matching search criteria.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFixturesByMonth",
            "description": "Get fixtures for a given month.",
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
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "matchId": {"type": "string"},
                        "homeTeam": {"type": "string"},
                        "awayTeam": {"type": "string"},
                        "date": {"type": "string", "format": "date-time"},
                    },
                },
                "description": "List of fixtures for the given month.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getAllFixtures",
            "description": "Get all fixtures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "matchId": {"type": "string"},
                        "homeTeam": {"type": "string"},
                        "awayTeam": {"type": "string"},
                        "date": {"type": "string", "format": "date-time"},
                    },
                },
                "description": "List of all fixtures.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getTrainingsByMonth",
            "description": "Get training sessions for a month.",
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
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trainingId": {"type": "string"},
                        "date": {"type": "string", "format": "date-time"},
                        "location": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
                "description": "List of training sessions.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getLineups",
            "description": "Retrieve match lineups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matchId": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["matchId", "clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "object",
                "properties": {
                    "homeTeamLineup": {"type": "object"},
                    "awayTeamLineup": {"type": "object"},
                },
                "description": "Lineups for both teams.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getEvents",
            "description": "Retrieve events for a match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matchId": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["matchId", "clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of match events.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getResult",
            "description": "Retrieve the result of a match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matchId": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["matchId", "clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "object",
                "properties": {
                    "homeScore": {"type": "integer"},
                    "awayScore": {"type": "integer"},
                    "updatedAt": {"type": "string", "format": "date-time"},
                },
                "description": "Match result including scores and update timestamp.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getPlayerRating",
            "description": "Fetches players rating for a specific match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matchId": {"type": "string"},
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["matchId", "clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "playerEmail": {"type": "string"},
                        "createdAt": {"type": "string"},
                        "additionalProperties": {"type": "number"},
                    },
                },
                "description": "List of player ratings for the match.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getRides",
            "description": "Retrieve available rides for a team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "driverName": {"type": "string"},
                        "seats": {"type": "integer"},
                        "location": {"type": "string"},
                        "time": {"type": "string"},
                        "matchDetails": {"type": "string"},
                    },
                },
                "description": "List of available carpool rides.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listProducts",
            "description": "Retrieve available products for a specific team inside a club.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique product ID from Firestore.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the product.",
                        },
                        "price": {
                            "type": "number",
                            "format": "float",
                            "description": "Base price of the product in EUR.",
                        },
                        "installmentMonths": {
                            "type": "integer",
                            "description": "Number of months for installment plan (null for full payment).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Category of the product.",
                        },
                        "isMembership": {
                            "type": "boolean",
                            "description": "Indicates if the product is a membership.",
                        },
                        "stripe_product_id": {
                            "type": "string",
                            "description": "The Stripe product ID linked to this product.",
                        },
                        "stripe_price_id": {
                            "type": "string",
                            "description": "The Stripe price ID linked to this product.",
                        },
                    },
                },
                "description": "List of available products for the specific team inside the club.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listTransactions",
            "description": "Retrieve a user's transaction history, including completed and pending transactions with itemized details of purchased products.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division", "email"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique transaction ID.",
                        },
                        "amount": {
                            "type": "number",
                            "format": "float",
                            "description": "Transaction amount in EUR.",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Currency of the transaction.",
                        },
                        "status": {
                            "type": "string",
                            "description": "Payment status (e.g., completed, pending).",
                        },
                        "club": {
                            "type": "string",
                            "description": "The club where the transaction was made.",
                        },
                        "ageGroup": {
                            "type": "string",
                            "description": "Age group related to the transaction.",
                        },
                        "division": {
                            "type": "string",
                            "description": "Division related to the transaction.",
                        },
                        "timestamp": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Timestamp when the transaction was recorded.",
                        },
                        "purchasedItems": {
                            "type": "array",
                            "description": "List of purchased products in the transaction.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "productId": {
                                        "type": "string",
                                        "description": "Stripe price ID of the product.",
                                    },
                                    "productName": {
                                        "type": "string",
                                        "description": "Name of the purchased product.",
                                    },
                                    "category": {
                                        "type": "string",
                                        "description": "Category of the product.",
                                        "enum": [
                                            "membership",
                                            "merchandise",
                                            "training",
                                            "match",
                                            "other",
                                        ],
                                    },
                                    "quantity": {
                                        "type": "integer",
                                        "description": "Quantity of the product purchased.",
                                    },
                                    "installmentMonths": {
                                        "type": "integer",
                                        "description": "Number of months for installment plan (null for one-time payment).",
                                    },
                                    "totalPrice": {
                                        "type": "number",
                                        "format": "float",
                                        "description": "Total price paid for this product.",
                                    },
                                },
                            },
                        },
                    },
                },
                "description": "List of transactions for the specified user, including itemized purchase details.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getPlayerStats",
            "description": "Fetches player statistics based on their email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                    "playerEmail": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division", "playerEmail"],
            },
            "returns": {
                "type": "object",
                "properties": {
                    "playerEmail": {"type": "string"},
                    "playerName": {"type": "string"},
                    "goals": {"type": "integer"},
                    "assists": {"type": "integer"},
                    "yellowCards": {"type": "integer"},
                    "redCards": {"type": "integer"},
                },
                "description": "Fetches player statistics based on their email.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchPlayersByName",
            "description": "Searches for players based on a partial or full match of their name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                    "playerName": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division", "playerName"],
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "playerEmail": {"type": "string"},
                        "playerName": {"type": "string"},
                        "goals": {"type": "integer"},
                        "assists": {"type": "integer"},
                        "yellowCards": {"type": "integer"},
                        "redCards": {"type": "integer"},
                    },
                },
                "description": "List of player ratings for the match.",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listAllPlayerStats",
            "description": "Retrieves all player statistics and identifies top performers for various categories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clubName": {"type": "string"},
                    "ageGroup": {"type": "string"},
                    "division": {"type": "string"},
                },
                "required": ["clubName", "ageGroup", "division"],
            },
            "returns": {
                "type": "object",
                "properties": {
                    "leaderboard": {
                        "type": "object",
                        "properties": {
                            "topScorer": {
                                "type": "object",
                                "properties": {
                                    "playerName": {"type": "string"},
                                    "goals": {"type": "integer"},
                                },
                            },
                            "mostAssists": {
                                "type": "object",
                                "properties": {
                                    "playerName": {"type": "string"},
                                    "assists": {"type": "integer"},
                                },
                            },
                            "mostYellowCards": {
                                "type": "object",
                                "properties": {
                                    "playerName": {"type": "string"},
                                    "yellowCards": {"type": "integer"},
                                },
                            },
                            "mostRedCards": {
                                "type": "object",
                                "properties": {
                                    "playerName": {"type": "string"},
                                    "redCards": {"type": "integer"},
                                },
                            },
                        },
                    },
                    "allPlayers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "playerEmail": {"type": "string"},
                                "playerName": {"type": "string"},
                                "goals": {"type": "integer"},
                                "assists": {"type": "integer"},
                                "yellowCards": {"type": "integer"},
                                "redCards": {"type": "integer"},
                            },
                        },
                        "description": "List of all players and their statistics.",
                    },
                },
                "description": "Leaderboard with top performers and all player statistics.",
            },
        },
    },
]


# --------------------------------------------------------------------------------
# 6) The system prompt
# --------------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a helpful AI assistant for Grassroots Football Management.

Today's date is {current_date}, formatted as YYYY-MM-DD (Year-Month-Day).

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

        # Get current date in YYYY-MM-DD format
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Build system + user messages
        system_prompt = SYSTEM_PROMPT.format(
            current_date=current_date,
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

                if fn_name == "getPlayers":
                    reply = call_external_service(
                        "getPlayers",
                        "/club/players",
                        fn_args,
                        id_token,
                        user_message,
                    )

                elif fn_name == "listTeamMembers":
                    reply = call_external_service(
                        "listTeamMembers",
                        "/membership/team",
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
                elif fn_name == "getFixturesByMonth":
                    reply = call_external_service(
                        "getFixturesByMonth",
                        "/schedule/fixture",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getAllFixtures":
                    reply = call_external_service(
                        "getAllFixtures",
                        "/schedule/fixtures",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getTrainingsByMonth":
                    reply = call_external_service(
                        "getTrainingsByMonth",
                        "/schedule/training",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getLineups":
                    reply = call_external_service(
                        "getLineups",
                        "/fixture/lineups",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getEvents":
                    reply = call_external_service(
                        "getEvents",
                        "/fixture/events",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "getResult":
                    reply = call_external_service(
                        "getResult",
                        "/fixture/results",
                        {},
                        id_token,
                        user_message,
                    )
                elif fn_name == "getPlayerRating":
                    reply = call_external_service(
                        "getPlayerRating",
                        "/fixture/player",
                        {},
                        id_token,
                        user_message,
                    )
                elif fn_name == "getRides":
                    reply = call_external_service(
                        "getRides",
                        "/carpool/rides",
                        fn_args,
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
                elif fn_name == "getPlayerStats":
                    reply = call_external_service(
                        "getPlayerStats",
                        "/stats/get",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "searchPlayersByName":
                    reply = call_external_service(
                        "searchPlayersByName",
                        "/stats/search",
                        fn_args,
                        id_token,
                        user_message,
                    )
                elif fn_name == "listAllPlayerStats":
                    reply = call_external_service(
                        "listAllPlayerStats",
                        "/stats/list",
                        fn_args,
                        id_token,
                        user_message,
                    )
                else:
                    reply = "Unknown function call received."

                if reply:
                    replies.append(reply)

            return jsonify({"reply": "\n".join(replies)}), 200

        elif not msg.tool_calls:
            # If no function call is made but relevant data is requested, force a function call.
            if "players" in user_message.lower() or "members" in user_message.lower():
                # If user is asking for team members, force a function call to listTeamMembers
                fn_name = "listTeamMembers"
            elif "fixtures" in user_message.lower():
                # If user is asking for fixtures, force a function call to getAllFixtures
                fn_name = "getAllFixtures"
            elif (
                "products" in user_message.lower()
                or "merchandise" in user_message.lower()
            ):
                fn_name = "listProducts"
            elif (
                "transactions" in user_message.lower()
                or "payments" in user_message.lower()
            ):
                fn_name = "listTransactions"
            else:
                # No relevant function to force call
                final_text = msg.content
                return jsonify({"reply": final_text}), 200

            # If we reach here, it means we manually forced a function call
            forced_reply = call_external_service(
                fn_name,
                f"/{fn_name.replace('list', '').replace('get', '').lower()}",
                fn_args,
                id_token,
                user_message,
            )
            return jsonify({"reply": forced_reply}), 200

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

- **DO NOT** use markdown (`*`, `_`, `-`, `#`, `>`, backticks, etc.).
- **DO NOT** format responses with markdown-style lists or bold/italic.
- Use simple plain text.
- Structure responses using clear sentence formatting.

Explain the significance of the data where relevant.
""",
            },
            {
                "role": "user",
                "content": f"The user asked: {original_user_message}. Here is the data you retrieved: {json.dumps(data)}",
            },
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
