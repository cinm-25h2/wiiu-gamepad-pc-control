#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
APP="${APP:-${BASE}/wiiu_drc_gui.py}"
HOST="${WIIU_GUI_HOST:-0.0.0.0}"
PORT="${WIIU_GUI_PORT:-8765}"

mkdir -p "${BASE}/gui-logs"
nohup python3 "${APP}" --host "${HOST}" --port "${PORT}" \
  > "${BASE}/gui.log" 2>&1 &
echo "$!" > "${BASE}/gui.pid"
sleep 1
echo "GUI started: http://${HOST}:${PORT}/"
echo "Token is stored at ${BASE}/gui-token and is not printed."
echo "Open with: http://<ubuntu-host-ip>:${PORT}/?token=<token>"
