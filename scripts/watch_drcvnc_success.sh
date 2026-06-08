#!/usr/bin/env bash
set -u

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"
OFFSET="${DRC_TSF_BOOTTIME_OFFSET_US:-}"
INTERVAL="${INTERVAL:-10}"
START_DESKTOP="${START_DESKTOP:-1}"
START_XEV="${START_XEV:-0}"
OPEN_FILE_MANAGER="${OPEN_FILE_MANAGER:-0}"
MEASURE_BEFORE_RESTART="${MEASURE_BEFORE_RESTART:-1}"

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

station_mac() {
  timeout 3 iw dev "${AP_IF}" station dump 2>/dev/null |
    awk '/^Station / { print $2; exit }'
}

while true; do
  live_offset="$(current_stream_offset || true)"
  if [[ -n "${live_offset}" ]]; then
    OFFSET="${live_offset}"
    printf '%s\n' "${OFFSET}" > "${BASE}/last_tsf_offset.conf"
  fi

  if ! pgrep -x drcvncclient >/dev/null 2>&1 ||
     ! pgrep -x Xtigervnc >/dev/null 2>&1; then
    mac="$(station_mac || true)"
    if [[ -z "${mac}" ]]; then
      log "stream process missing but no GamePad station is associated; waiting"
      sleep "${INTERVAL}"
      continue
    fi
    if [[ "${MEASURE_BEFORE_RESTART}" = "1" ]]; then
      log "stream process missing; measuring TSF on the current AP before restart"
      if PAD_DETECT_TIMEOUT=15 RESTART_AP=0 RUN_NETBOOT=1 \
          "${BASE}/run_wiiu_gamepad_screen_success.sh"; then
        OFFSET="$(saved_offset)"
      else
        log "TSF measurement failed; waiting"
        sleep "${INTERVAL}"
        continue
      fi
    fi
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
