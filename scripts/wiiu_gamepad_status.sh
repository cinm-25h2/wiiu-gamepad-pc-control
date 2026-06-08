#!/usr/bin/env bash
set -u

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"
HOSTAPD_CLI="${HOSTAPD_CLI:-${BASE}/third_party/drc-hostap/hostapd/hostapd_cli}"

echo "== AP state =="
pgrep -a hostapd || true
pgrep -a dnsmasq || true
if [[ -x "${HOSTAPD_CLI}" ]]; then
  timeout 3 "${HOSTAPD_CLI}" -i "${AP_IF}" status 2>/dev/null |
    sed -n '/^state=/p;/^freq=/p;/^channel=/p;/^ssid\[0\]=/p;/^num_sta\[0\]=/p' || true
fi
timeout 3 iw dev "${AP_IF}" info 2>/dev/null | sed -n '/Interface /p;/type /p;/channel /p' || true
ip -br addr show "${AP_IF}" 2>/dev/null || true
echo

echo "== AP station summary =="
station_mac="$(timeout 3 iw dev "${AP_IF}" station dump 2>/dev/null |
  awk '/^Station / { print $2; exit }' || true)"
if [[ -n "${station_mac}" ]]; then
  echo "detected GamePad/station: ${station_mac}"
else
  echo "detected GamePad/station: none"
fi
if [[ -s "${BASE}/gamepad_mac.conf" ]]; then
  echo "last saved GamePad MAC: $(tr -d '[:space:]' < "${BASE}/gamepad_mac.conf")"
fi
echo

echo "== stream processes =="
pgrep -a pad_probe || true
pgrep -a drcvncclient || true

pid="$(pgrep -n drcvncclient || pgrep -n pad_probe || true)"
if [[ -n "${pid}" ]]; then
  echo
  echo "== stream env =="
  strings "/proc/${pid}/environ" | grep -E '^DRC_|^LD_LIBRARY_PATH=' | sort || true
fi

echo
echo "== station =="
timeout 3 iw dev "${AP_IF}" station dump 2>/dev/null | sed -n '1,32p' || true

echo
echo "== DHCP leases =="
cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true

echo
echo "== sockets =="
ss -lunp 2>/dev/null | grep -E 'pad_probe|drcvncclient' || true

echo
echo "== drcvncclient log tail =="
tail -n 20 "${BASE}/drcvncclient.log" 2>/dev/null || true

if pgrep pad_probe >/dev/null 2>&1; then
  echo
  echo "== pad_probe log tail =="
  tail -n 30 "${BASE}/pad_probe.log" 2>/dev/null || true
fi
