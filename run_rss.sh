#!/bin/bash
set -euo pipefail
REPO_DIR="/home/guosq/.openclaw/workspace/stanley-rss-reader"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
cd "$REPO_DIR"
source "$VENV/bin/activate"

MQTT_CRED_FILE="/home/guosq/.openclaw/workspace/mqtt/credentials.txt"
if [ -f "$MQTT_CRED_FILE" ]; then
  export MQTT_HOST="127.0.0.1"
  export MQTT_PORT="1883"
  export MQTT_USERNAME="$(grep '^MQTT_USERNAME=' "$MQTT_CRED_FILE" | cut -d= -f2-)"
  export MQTT_PASSWORD="$(grep '^MQTT_PASSWORD=' "$MQTT_CRED_FILE" | cut -d= -f2-)"
fi

python scripts/fetch_rss.py --limit 20 --git
