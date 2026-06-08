#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
PAD_IP="${PAD_IP:-192.168.1.11}"
DISPLAY_NUM="${DISPLAY_NUM:-1}"
VNC_GEOMETRY="${VNC_GEOMETRY:-864x480}"
START_DESKTOP="${START_DESKTOP:-0}"
START_XEV="${START_XEV:-0}"
OPEN_FILE_MANAGER="${OPEN_FILE_MANAGER:-0}"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-${BASE}/xdg-runtime-root}"

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

offset="${DRC_TSF_BOOTTIME_OFFSET_US:-}"
if [[ -z "${offset}" ]]; then
  offset="$(current_stream_offset || true)"
fi
if [[ -z "${offset}" ]]; then
  offset="$(cat "${BASE}/last_tsf_offset.conf" 2>/dev/null || true)"
fi
if [[ -z "${offset}" ]]; then
  echo "No TSF offset available. Run this first:" >&2
  echo "  RESTART_AP=0 ${BASE}/run_wiiu_gamepad_screen_success.sh" >&2
  exit 1
fi
printf '%s\n' "${offset}" > "${BASE}/last_tsf_offset.conf"

mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}"
mkdir -p /root/.config/lxpanel/LXDE/panels /root/Desktop
if [[ -r /etc/xdg/lxpanel/default/panels/panel &&
      ! -r /root/.config/lxpanel/LXDE/panels/panel ]]; then
  cp /etc/xdg/lxpanel/default/panels/panel \
    /root/.config/lxpanel/LXDE/panels/panel
fi
export XDG_RUNTIME_DIR
export WIIU_BASE="${BASE}"
export WIIU_START_DESKTOP="${START_DESKTOP}"
export WIIU_START_XEV="${START_XEV}"
export WIIU_OPEN_FILE_MANAGER="${OPEN_FILE_MANAGER}"

cat > "${BASE}/vnc-xstartup" <<'EOF_XSTARTUP'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=LXDE
export DESKTOP_SESSION=LXDE
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
  export XDG_RUNTIME_DIR=/tmp/wiiu-vnc-runtime
fi
mkdir -p "${XDG_RUNTIME_DIR}" 2>/dev/null || true
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

show_marker() {
  xsetroot -solid '#18242f' 2>/dev/null || true
  xterm -geometry 80x18+20+20 -title "Wii U GamePad PC" \
    -e sh -c 'while :; do
      clear 2>/dev/null || true
      date
      echo
      echo "Wii U GamePad PC stream"
      echo
      echo "Touch acts as mouse."
      echo "Buttons map to VNC events."
      sleep 1
    done' &
}

if [ "${WIIU_START_DESKTOP:-0}" = "1" ] && command -v openbox >/dev/null 2>&1; then
  xsetroot -solid '#20303a' 2>/dev/null || true
  dbus-launch --exit-with-session sh -c '
    openbox >/tmp/wiiu-openbox.log 2>&1 &
    sleep 1
    if command -v pcmanfm >/dev/null 2>&1; then
      pcmanfm --desktop --profile LXDE >/tmp/wiiu-pcmanfm.log 2>&1 &
      if [ "${WIIU_OPEN_FILE_MANAGER:-0}" = "1" ] && [ -n "${WIIU_BASE:-}" ]; then
        pcmanfm "${WIIU_BASE}" >/tmp/wiiu-pcmanfm-window.log 2>&1 &
      fi
    fi
    if command -v lxpanel >/dev/null 2>&1; then
      lxpanel --profile LXDE >/tmp/wiiu-lxpanel.log 2>&1 &
    fi
    xterm -geometry 70x14+24+36 -title "Wii U GamePad PC" -e sh -c "while :; do clear 2>/dev/null || true; date; echo; echo Desktop mode; echo Touch and buttons are forwarded.; sleep 2; done" &
    wait
  ' &
else
  show_marker
fi

if [ "${WIIU_START_XEV:-0}" = "1" ]; then
  xev -geometry 260x170+585+285 -event mouse -event keyboard 2>/dev/null &
fi
tail -f /dev/null
EOF_XSTARTUP
chmod +x "${BASE}/vnc-xstartup"

log "stopping old drcvncclient and pad_probe"
killall -9 drcvncclient 2>/dev/null || true
killall -9 pad_probe 2>/dev/null || true
: > "${BASE}/pad_probe.log" 2>/dev/null || true

log "starting TigerVNC display :${DISPLAY_NUM}"
vncserver -kill ":${DISPLAY_NUM}" >/dev/null 2>&1 || true
vncserver ":${DISPLAY_NUM}" \
  -SecurityTypes None \
  -geometry "${VNC_GEOMETRY}" \
  -localhost yes \
  -xstartup "${BASE}/vnc-xstartup" \
  > "${BASE}/vncserver.log" 2>&1

log "starting drcvncclient"
cd "${BASE}/pc2drc/libdrc-vnc/drcvncclient/src"
LD_LIBRARY_PATH="${BASE}/local/lib" \
DRC_GAMEPAD_IP="${PAD_IP}" \
DRC_TSF_BOOTTIME_OFFSET_US="${offset}" \
DRC_BIND_MEDIA_SOURCE_PORTS=1 \
nohup ./drcvncclient ":${DISPLAY_NUM}" > "${BASE}/drcvncclient.log" 2>&1 &
echo $! > "${BASE}/drcvncclient.pid"

sleep 3
pgrep -a drcvncclient || true
tail -n 80 "${BASE}/drcvncclient.log" || true
