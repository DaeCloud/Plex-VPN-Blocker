import os
import requests
from flask import Flask, request, jsonify
import json
import logging

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables
PLEX_SERVER_URL = os.getenv("PLEX_SERVER_URL", "http://127.0.0.1:32400")  # Default to localhost if not set
PLEX_API_TOKEN = os.getenv("PLEX_API_TOKEN", "")
VPN_API_KEY = os.getenv("VPN_API_KEY", "")
TEST_BLOCKED_IP = os.getenv("TEST_BLOCKED_IP", "")
IGNORED_USERNAMES = os.getenv("IGNORED_USERNAMES", "")

if not PLEX_API_TOKEN:
    raise ValueError("PLEX_API_TOKEN environment variable is required")
if not VPN_API_KEY:
    raise ValueError("VPN_API_KEY environment variable is required")

# Convert the comma-separated list of ignored usernames into a set for faster lookup
ignored_usernames_set = set(IGNORED_USERNAMES.split(","))

def check_vpn_usage(ip_address):
    """Check if the given IP address is using a VPN."""
    if ip_address == TEST_BLOCKED_IP:
        logging.info(f"Test blocked IP match: {ip_address}")
        return True
    url = f"https://vpnapi.io/api/{ip_address}?key={VPN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("security", {}).get("vpn", False)  # Return True if VPN is detected
    else:
        logging.error(f"Failed to query VPN API: {response.status_code} - {response.text}")
        raise Exception(f"VPN API error: {response.status_code} - {response.text}")

def get_session_id(machine_identifier):
    """Fetch the session ID for a given machine identifier from the Plex Active Sessions API."""
    url = f"{PLEX_SERVER_URL}/status/sessions"
    headers = {
        "X-Plex-Token": PLEX_API_TOKEN
    }
    logging.info(f"Querying Active Sessions API for machine identifier: {machine_identifier}")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        sessions = response.json().get("MediaContainer", {}).get("Metadata", [])
        for session in sessions:
            player = session.get("Player", {})
            if player.get("machineIdentifier") == machine_identifier:
                session_id = player.get("sessionKey")
                logging.info(f"Found session ID {session_id} for machine identifier {machine_identifier}")
                return session_id
        logging.warning(f"No matching session found for machine identifier: {machine_identifier}")
        return None
    else:
        logging.error(f"Failed to query Active Sessions API: {response.status_code} - {response.text}")
        return None

def stop_playback(session_id):
    """Send a request to stop playback for a specific session."""
    url = f"{PLEX_SERVER_URL}/status/sessions/terminate"
    params = {
        "sessionId": session_id,
        "reason": "Streaming from a VPN or blocked connection, please disconnect from your VPN and try again.",
        "X-Plex-Token": PLEX_API_TOKEN
    }
    logging.info(f"Sending request to stop playback for session ID: {session_id}")
    response = requests.get(url, params=params)
    if response.status_code == 200:
        logging.info(f"Playback successfully stopped for session ID: {session_id}")
        return True
    else:
        logging.error(f"Failed to stop playback: {response.status_code} - {response.text}")
        return False

def stop_playback_by_machine_identifier(machine_identifier):
    """Fetch session ID and stop playback using it."""
    session_id = get_session_id(machine_identifier)
    if not session_id:
        logging.error(f"Cannot stop playback; session ID not found for machine identifier: {machine_identifier}")
        return False

    return stop_playback(session_id)

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming Plex webhooks."""
    logging.info("Received a webhook request.")

    # Check if the content type is multipart/form-data
    if request.content_type.startswith("multipart/form-data"):
        payload = request.form.get("payload")
        if payload:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logging.error("Invalid JSON in payload.")
                return jsonify({"status": "Invalid JSON in payload"}), 400
        else:
            logging.error("No payload found in multipart request.")
            return jsonify({"status": "No payload found in multipart request"}), 400
    else:
        # For other content types, assume JSON body
        data = request.json
        if not data:
            logging.error("Invalid or missing JSON payload.")
            return jsonify({"status": "Invalid or missing JSON payload"}), 400

    # Check if the event is a playback start event
    event_type = data.get("event", "")
    if event_type != "media.play":
        logging.info(f"Ignored non-playback event: {event_type}")
        return jsonify({"status": "Ignored non-playback event"}), 200

    # Extract IP, session, and user details
    client_ip = data.get("Player", {}).get("publicAddress", "")
    machine_identifier = data.get("Player", {}).get("uuid", "")
    username = data.get("Account", {}).get("title", "")

    logging.info(f"Event details - Username: {username}, Client IP: {client_ip}, Machine Identifier: {machine_identifier}")

    if not client_ip:
        logging.error("Client IP not found in webhook payload.")
        return jsonify({"status": "Client IP not found in webhook payload"}), 400

    # Check if the username is in the ignored list
    if username in ignored_usernames_set:
        logging.info(f"Playback allowed for ignored username: {username}")
        return jsonify({"status": "Playback allowed for ignored username"}), 200

    # Check if the IP is using a VPN
    try:
        is_vpn = check_vpn_usage(client_ip)
    except Exception as e:
        logging.error(f"Error querying VPN API: {e}")
        return jsonify({"status": "Error querying VPN API", "error": str(e)}), 500

    if is_vpn:
        if machine_identifier:
            success = stop_playback_by_machine_identifier(machine_identifier)
            if success:
                return jsonify({"status": "Playback stopped for VPN user"}), 200
            return jsonify({"status": "Failed to stop playback"}), 500
        logging.error("Machine Identifier not found for VPN user.")
        return jsonify({"status": "Machine Identifier not found"}), 400

    logging.info(f"Playback allowed for IP: {client_ip}")
    return jsonify({"status": "Playback allowed"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10201)
