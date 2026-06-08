#!/usr/bin/env bash
set -u

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"

echo "== AP station summary =="
station_mac="$(iw dev "${AP_IF}" station dump 2>/dev/null |
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
iw dev "${AP_IF}" station dump 2>/dev/null | sed -n '1,32p' || true

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
