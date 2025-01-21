import os
import requests
from flask import Flask, request, jsonify
import json
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("plex_webhook.log")  # Logs will also be saved to a file
    ]
)

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
    if ip_address == TEST_BLOCKED_IP:
        logging.info(f"IP address {ip_address} matches the test blocked IP.")
        return True
    url = f"https://vpnapi.io/api/{ip_address}?key={VPN_API_KEY}"
    logging.info(f"Checking VPN usage for IP address: {ip_address}")
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        is_vpn = data.get("security", {}).get("vpn", False)
        logging.info(f"VPN check result for {ip_address}: {'VPN detected' if is_vpn else 'No VPN detected'}")
        return is_vpn
    else:
        logging.error(f"Failed to query VPN API for {ip_address}: {response.status_code} - {response.text}")
        raise Exception(f"Failed to query VPN API: {response.status_code} - {response.text}")

def stop_playback(session_id):
    url = f"{PLEX_SERVER_URL}/status/sessions/terminate"
    params = {
        "sessionId": session_id,
        "reason": "Streaming from a VPN or blocked connection, please disconnect from your VPN and try again.",
        "X-Plex-Token": PLEX_API_TOKEN
    }
    logging.info(f"Attempting to stop playback for session ID: {session_id}")
    response = requests.get(url, params=params)
    if response.status_code == 200:
        logging.info(f"Successfully stopped playback for session ID: {session_id}")
        return True
    else:
        logging.error(f"Failed to stop playback for session ID {session_id}: {response.status_code} - {response.text}")
        return False

@app.route("/webhook", methods=["POST"])
def webhook():
    logging.info("Received a webhook request.")
    # Check if the content type is multipart/form-data
    if request.content_type.startswith("multipart/form-data"):
        payload = request.form.get("payload")
        if payload:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logging.error("Invalid JSON in payload from multipart request.")
                return jsonify({"status": "Invalid JSON in payload"}), 400
        else:
            logging.error("No payload found in multipart request.")
            return jsonify({"status": "No payload found in multipart request"}), 400
    else:
        data = request.json
        if not data:
            logging.error("Invalid or missing JSON payload in request.")
            return jsonify({"status": "Invalid or missing JSON payload"}), 400

    # Log incoming event
    logging.info(f"Webhook event received: {data.get('event', 'Unknown')}")

    # Check if the event is a playback start event
    event_type = data.get("event", "")
    if event_type != "media.play":
        logging.info(f"Ignored non-playback event: {event_type}")
        return jsonify({"status": "Ignored non-playback event"}), 200

    # Extract IP and session details
    client_ip = data.get("Player", {}).get("publicAddress", "")
    session_id = data.get("Session", {}).get("id", "")
    username = data.get("Account", {}).get("title", "")

    logging.info(f"Event details - Username: {username}, Client IP: {client_ip}, Session ID: {session_id}")

    if not client_ip:
        logging.error("Client IP not found in webhook payload.")
        return jsonify({"status": "Client IP not found in webhook payload"}), 400

    if username in ignored_usernames_set:
        logging.info(f"Playback allowed for ignored username: {username}")
        return jsonify({"status": "Playback allowed for ignored username"}), 200

    try:
        is_vpn = check_vpn_usage(client_ip)
    except Exception as e:
        logging.error(f"Error querying VPN API: {e}")
        return jsonify({"status": "Error querying VPN API", "error": str(e)}), 500

    if is_vpn:
        if session_id:
            success = stop_playback(session_id)
            if success:
                return jsonify({"status": "Playback stopped for VPN user"}), 200
            return jsonify({"status": "Failed to stop playback"}), 500
        logging.error("Session ID not found for VPN user.")
        return jsonify({"status": "Session ID not found"}), 400

    logging.info(f"Playback allowed for IP: {client_ip}")
    return jsonify({"status": "Playback allowed"}), 200

if __name__ == "__main__":
    logging.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=10201)
