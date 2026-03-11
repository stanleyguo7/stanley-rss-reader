#!/bin/bash
set -euo pipefail
REPO_DIR="/home/guosq/.openclaw/workspace/stanley-rss-reader"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
cd "$REPO_DIR"
source "$VENV/bin/activate"
python scripts/fetch_rss.py --limit 3 --git
