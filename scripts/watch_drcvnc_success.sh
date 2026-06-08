#!/usr/bin/env bash
set -u

BASE="${BASE:-/root/wiiu-drc}"
OFFSET="${DRC_TSF_BOOTTIME_OFFSET_US:-}"
INTERVAL="${INTERVAL:-10}"
START_DESKTOP="${START_DESKTOP:-1}"
START_XEV="${START_XEV:-0}"
OPEN_FILE_MANAGER="${OPEN_FILE_MANAGER:-0}"

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"
}

current_stream_offset() {
  local pid
  pid="$(pgrep -n drcvncclient || pgrep -n pad_probe || true)"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  strings "/proc/${pid}/environ" |
    sed -n 's/^DRC_TSF_BOOTTIME_OFFSET_US=//p' |
    tail -n 1
}

saved_offset() {
  cat "${BASE}/last_tsf_offset.conf" 2>/dev/null || true
}

while true; do
  live_offset="$(current_stream_offset || true)"
  if [[ -n "${live_offset}" ]]; then
    OFFSET="${live_offset}"
    printf '%s\n' "${OFFSET}" > "${BASE}/last_tsf_offset.conf"
  fi

  if ! pgrep -x drcvncclient >/dev/null 2>&1 ||
     ! pgrep -x Xtigervnc >/dev/null 2>&1; then
    if [[ -z "${OFFSET}" ]]; then
      OFFSET="$(saved_offset)"
    fi
    if [[ -z "${OFFSET}" ]]; then
      log "stream process missing but no TSF offset is known; waiting"
      sleep "${INTERVAL}"
      continue
    fi
    log "stream process missing; restarting VNC stream"
    DRC_TSF_BOOTTIME_OFFSET_US="${OFFSET}" \
    START_DESKTOP="${START_DESKTOP}" \
    START_XEV="${START_XEV}" \
    OPEN_FILE_MANAGER="${OPEN_FILE_MANAGER}" \
      "${BASE}/start_drcvnc_success.sh"
  fi
  sleep "${INTERVAL}"
done
