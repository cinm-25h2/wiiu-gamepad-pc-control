#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
PAD_MAC="${PAD_MAC:-}"
AP_IF="${AP_IF:-ap0}"
PHY_IF="${PHY_IF:-wlp0s20f3}"
CHANNEL="${CHANNEL:-48}"
PAD_IP="${PAD_IP:-192.168.1.11}"
CAPTURE_TIMEOUT="${CAPTURE_TIMEOUT:-90}"
CAPTURE_COUNT="${CAPTURE_COUNT:-20}"
PAD_DETECT_TIMEOUT="${PAD_DETECT_TIMEOUT:-90}"
RESTART_AP="${RESTART_AP:-1}"
RUN_NETBOOT="${RUN_NETBOOT:-1}"
NETBOOT="${NETBOOT:-${BASE}/third_party/drc-hostap/netboot/netboot}"

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"
}

cleanup_mon() {
  ip link set mon0 down 2>/dev/null || true
  iw dev mon0 del 2>/dev/null || true
}

current_station_mac() {
  timeout 3 iw dev "${AP_IF}" station dump 2>/dev/null |
    awk '/^Station / { print $2; exit }'
}

detect_gamepad_mac() {
  local mac=""
  local i

  for ((i = 0; i < PAD_DETECT_TIMEOUT; i++)); do
    mac="$(current_station_mac || true)"
    if [[ -n "${mac}" ]]; then
      printf '%s\n' "${mac}"
      return 0
    fi
    sleep 1
  done

  return 1
}

wait_for_configured_gamepad() {
  local i
  local seen

  for ((i = 0; i < PAD_DETECT_TIMEOUT; i++)); do
    seen="$(current_station_mac || true)"
    if [[ -n "${seen}" ]]; then
      if [[ -z "${PAD_MAC}" || "${seen,,}" = "${PAD_MAC,,}" ]]; then
        printf '%s\n' "${seen}"
        return 0
      fi
      log "station ${seen} is associated; waiting for ${PAD_MAC}"
    fi
    sleep 1
  done

  return 1
}

send_netboot() {
  if [[ "${RUN_NETBOOT}" = "1" && -x "${NETBOOT}" && -n "${PAD_MAC}" ]]; then
    log "sending netboot handshake to ${PAD_MAC}"
    timeout 25 "${NETBOOT}" 192.168.1.255 192.168.1.10 "${PAD_IP}" "${PAD_MAC}" || true
  fi
}

measure_tsf_offset() {
  cleanup_mon
  iw dev "${PHY_IF}" interface add mon0 type monitor ||
    iw dev "${AP_IF}" interface add mon0 type monitor
  ip link set mon0 up

  rm -f /tmp/wiiu_tsf.pcap /tmp/wiiu_tsf_capture.log /tmp/wiiu_measure_tsf.err
  log "capturing radiotap TSFT for ${PAD_MAC}"
  timeout "${CAPTURE_TIMEOUT}" tcpdump -i mon0 -s 256 -w /tmp/wiiu_tsf.pcap \
    -c "${CAPTURE_COUNT}" "wlan host ${PAD_MAC}" \
    >/tmp/wiiu_tsf_capture.log 2>&1 &
  local tcpdump_pid=$!

  while kill -0 "${tcpdump_pid}" 2>/dev/null; do
    if iw dev "${AP_IF}" station dump | grep -q "${PAD_MAC}"; then
      ping -c 1 -W 1 "${PAD_IP}" >/dev/null 2>&1 || true
    fi
    sleep 1
  done
  wait "${tcpdump_pid}" 2>/dev/null || true
  cleanup_mon

  local offset
  offset=$(python3 "${BASE}/measure_tsf_offset.py" /tmp/wiiu_tsf.pcap \
    2>/tmp/wiiu_measure_tsf.err || true)
  if [[ -z "${offset}" ]]; then
    log "failed to measure TSF offset"
    cat /tmp/wiiu_tsf_capture.log >&2 || true
    cat /tmp/wiiu_measure_tsf.err >&2 || true
    exit 1
  fi

  log "measured DRC_TSF_BOOTTIME_OFFSET_US=${offset}"
  cat /tmp/wiiu_measure_tsf.err >&2 || true
  printf '%s\n' "${offset}"
}

killall -9 pad_probe 2>/dev/null || true

if [[ "${RESTART_AP}" = "1" ]]; then
  log "restarting AP on channel ${CHANNEL}"
  CHANNEL="${CHANNEL}" "${BASE}/restart_wiiu_ap_keepalive.sh"
else
  log "keeping current AP; TSF must belong to this AP run"
fi

offset="${DRC_TSF_BOOTTIME_OFFSET_US:-}"
if [[ -z "${offset}" ]]; then
  if [[ -z "${PAD_MAC}" ]]; then
    log "waiting for GamePad station on ${AP_IF}"
    if ! PAD_MAC="$(wait_for_configured_gamepad)"; then
      log "no GamePad station appeared on ${AP_IF}"
      log "turn on the GamePad, or set PAD_MAC=xx:xx:xx:xx:xx:xx"
      exit 1
    fi
    log "detected GamePad station ${PAD_MAC}"
    printf '%s\n' "${PAD_MAC}" > "${BASE}/gamepad_mac.conf"
  else
    log "waiting for configured GamePad station ${PAD_MAC} on ${AP_IF}"
    if ! PAD_MAC="$(wait_for_configured_gamepad)"; then
      log "configured GamePad did not associate with ${AP_IF}"
      exit 1
    fi
  fi
  send_netboot
  offset="$(measure_tsf_offset | tail -n 1)"
fi
printf '%s\n' "${offset}" > "${BASE}/last_tsf_offset.conf"

cd "${BASE}"
: > pad_probe.log
cd "${BASE}/starter/apps/pad_probe"

log "starting pad_probe with success profile"
LD_LIBRARY_PATH="${BASE}/local/lib" \
DRC_GAMEPAD_IP="${PAD_IP}" \
DRC_TSF_BOOTTIME_OFFSET_US="${offset}" \
DRC_BIND_MEDIA_SOURCE_PORTS=1 \
nohup ./pad_probe > "${BASE}/pad_probe.log" 2>&1 &
echo $! > "${BASE}/pad_probe.pid"

sleep 2
if ! pgrep -a pad_probe; then
  log "pad_probe did not stay running"
  tail -n 80 "${BASE}/pad_probe.log" || true
  exit 1
fi
iw dev "${AP_IF}" station dump || true
ss -lunp | grep pad_probe || true
tail -n 60 "${BASE}/pad_probe.log" || true
if grep -qi "Unable to start streamer" "${BASE}/pad_probe.log"; then
  log "pad_probe reported streamer startup failure"
  exit 1
fi
