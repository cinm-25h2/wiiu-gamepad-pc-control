#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
WATCH="${BASE}/watch_drcvnc_success.sh"
PIDFILE="${BASE}/watch_drcvnc.pid"

mapfile -t pids < <(
  ps -eo pid=,args= |
    awk -v watch="${WATCH}" '$2 == "bash" && $3 == watch { print $1 }' |
    sort -n
)

if [[ "${#pids[@]}" -eq 0 ]]; then
  nohup "${WATCH}" > "${BASE}/watch_drcvnc.log" 2>&1 &
  echo "$!" > "${PIDFILE}"
  echo "WATCHDOG_STARTED $!"
  exit 0
fi

keep="${pids[-1]}"
for pid in "${pids[@]}"; do
  if [[ "${pid}" != "${keep}" ]]; then
    kill "${pid}" 2>/dev/null || true
  fi
done

echo "${keep}" > "${PIDFILE}"
echo "WATCHDOG_KEEP ${keep}"
ps -p "${keep}" -o pid=,args=
