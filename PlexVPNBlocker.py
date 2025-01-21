import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load environment variables
PLEX_SERVER_URL = os.getenv("PLEX_SERVER_URL", "http://127.0.0.1:32400")  # Default to localhost if not set
PLEX_API_TOKEN = os.getenv("PLEX_API_TOKEN", "")
VPN_API_KEY = os.getenv("VPN_API_KEY", "")
TEST_BLOCKED_IP = os.getenv("TEST_BLOCKED_IP", "")

if not PLEX_API_TOKEN:
    raise ValueError("PLEX_API_TOKEN environment variable is required")
if not VPN_API_KEY:
    raise ValueError("VPN_API_KEY environment variable is required")

def check_vpn_usage(ip_address):
    if ip_address == TEST_BLOCKED_IP:
        """Check if the given IP address matches the test address."""
        return true
    """Check if the given IP address is using a VPN."""
    url = f"https://vpnapi.io/api/{ip_address}?key={VPN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("security", {}).get("vpn", False)  # Return True if VPN is detected
    else:
        raise Exception(f"Failed to query VPN API: {response.status_code} - {response.text}")

def stop_playback(session_id):
    """Send a request to stop playback for a specific session."""
    url = f"{PLEX_SERVER_URL}/status/sessions/terminate"
    params = {
        "sessionId": session_id,
        "reason": "Streaming from a VPN or blocked connection, please disconnect from your VPN and try again.",
        "X-Plex-Token": PLEX_API_TOKEN
    }
    response = requests.get(url, params=params)
    return response.status_code == 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming Plex webhooks."""
    data = request.json

    # Check if the event is a playback start event
    event_type = data.get("event", "")
    if event_type != "media.play":
        return jsonify({"status": "Ignored non-playback event"}), 200

    # Extract IP and session details
    client_ip = data.get("Player", {}).get("publicAddress", "")
    session_id = data.get("Session", {}).get("id", "")

    if not client_ip:
        return jsonify({"status": "Client IP not found in webhook payload"}), 400

    # Check if the IP is using a VPN
    try:
        is_vpn = check_vpn_usage(client_ip)
    except Exception as e:
        return jsonify({"status": "Error querying VPN API", "error": str(e)}), 500

    if is_vpn:
        if session_id:
            success = stop_playback(session_id)
            if success:
                return jsonify({"status": "Playback stopped for VPN user"}), 200
            return jsonify({"status": "Failed to stop playback"}), 500
        return jsonify({"status": "Session ID not found"}), 400

    # If the IP is not using a VPN, allow playback
    return jsonify({"status": "Playback allowed"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10201)
