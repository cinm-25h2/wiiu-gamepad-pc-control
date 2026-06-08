#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run as root."
  exit 1
fi

install -d "${BASE}"
install -m 755 wiiu_drc_gui.py "${BASE}/wiiu_drc_gui.py"
install -m 755 scripts/*.sh "${BASE}/"
install -d "${BASE}/docs" "${BASE}/patches"
install -m 644 docs/*.md "${BASE}/docs/" 2>/dev/null || true
install -m 644 patches/*.patch "${BASE}/patches/" 2>/dev/null || true

echo "Installed to ${BASE}"
echo "Start GUI:"
echo "  ${BASE}/start_gui.sh"
