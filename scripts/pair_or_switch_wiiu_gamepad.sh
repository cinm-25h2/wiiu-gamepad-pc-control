#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"
CHANNEL="${CHANNEL:-48}"
PAD_IP="${PAD_IP:-192.168.1.11}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-180}"
RESTART_AP="${RESTART_AP:-1}"
RUN_NETBOOT="${RUN_NETBOOT:-1}"
NETBOOT="${NETBOOT:-${BASE}/third_party/drc-hostap/netboot/netboot}"

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"
}

detect_station() {
  iw dev "${AP_IF}" station dump 2>/dev/null |
    awk '/^Station / { print $2; exit }'
}

log "preparing Wii U GamePad AP for another already-paired GamePad"
log "if this GamePad is completely unpaired, pair it with the Wii U console first"

killall -9 drcvncclient 2>/dev/null || true
killall -9 pad_probe 2>/dev/null || true

if [[ "${RESTART_AP}" = "1" ]]; then
  CHANNEL="${CHANNEL}" "${BASE}/restart_wiiu_ap_keepalive.sh"
fi

log "turn on the target GamePad; waiting up to ${WAIT_TIMEOUT}s"
mac=""
for ((i = 0; i < WAIT_TIMEOUT; i++)); do
  mac="$(detect_station || true)"
  if [[ -n "${mac}" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "${mac}" ]]; then
  log "no GamePad associated with ${AP_IF}"
  exit 1
fi

printf '%s\n' "${mac}" > "${BASE}/gamepad_mac.conf"
log "detected GamePad MAC ${mac}"

if [[ "${RUN_NETBOOT}" = "1" && -x "${NETBOOT}" ]]; then
  log "sending netboot handshake to ${mac}"
  timeout 25 "${NETBOOT}" 192.168.1.255 192.168.1.10 "${PAD_IP}" "${mac}" || true
fi

log "ready. Start the screen with:"
log "  PAD_MAC=${mac} RESTART_AP=0 ${BASE}/run_wiiu_gamepad_screen_success.sh"
