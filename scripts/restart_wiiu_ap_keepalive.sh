#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"
PHY_IF="${PHY_IF:-wlp0s20f3}"
CHANNEL="${CHANNEL:-48}"
AP_IP="${AP_IP:-192.168.1.10/24}"
PAD_IP="${PAD_IP:-192.168.1.11}"
HOSTAPD="${HOSTAPD:-${BASE}/third_party/drc-hostap/hostapd/hostapd}"
CONF="${BASE}/wiiu_ap_keepalive.conf"
HOSTAPD_LOG="${BASE}/hostapd_wiiu.log"
DNSMASQ_LOG="${BASE}/dnsmasq_wiiu.log"
STA_CONF="${STA_CONF:-${BASE}/sta_parent.conf}"
STA_CONNECT_TIMEOUT="${STA_CONNECT_TIMEOUT:-30}"
REQUIRE_PARENT_STA="${REQUIRE_PARENT_STA:-1}"

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

[[ -x "${HOSTAPD}" ]] || fail "hostapd not found at ${HOSTAPD}"
[[ -r "${BASE}/get_psk.conf" ]] || fail "${BASE}/get_psk.conf is missing"

parent_sta_connected() {
  timeout 3 iw dev "${PHY_IF}" link 2>/dev/null | grep -q '^Connected'
}

ensure_parent_sta() {
  local i

  if [[ "${REQUIRE_PARENT_STA}" != "1" || ! -r "${STA_CONF}" ]]; then
    return 0
  fi
  if parent_sta_connected; then
    log "parent STA is already connected"
    return 0
  fi

  log "connecting parent STA before starting the 5 GHz AP"
  if command -v nmcli >/dev/null 2>&1; then
    nmcli dev set "${PHY_IF}" managed no >/dev/null 2>&1 || true
  fi
  pkill -f "wpa_supplicant.*${PHY_IF}" 2>/dev/null || true
  wpa_supplicant -B -i "${PHY_IF}" -c "${STA_CONF}" \
    -f "${BASE}/sta_parent_wpa_supplicant.log" >/dev/null 2>&1 || true

  for ((i = 0; i < STA_CONNECT_TIMEOUT; i++)); do
    if parent_sta_connected; then
      log "parent STA connected"
      return 0
    fi
    sleep 1
  done

  log "parent STA did not connect; Intel LAR may prevent AP beaconing"
}

export BASE AP_IF CHANNEL CONF
python3 - <<'PY'
from pathlib import Path
import os

base = Path(os.environ["BASE"])
ap_if = os.environ["AP_IF"]
channel = os.environ["CHANNEL"]
conf = Path(os.environ["CONF"])

ssid = None
psk = None
for raw in (base / "get_psk.conf").read_text().splitlines():
    line = raw.strip()
    if line.startswith("ssid="):
        ssid = line.split("=", 1)[1].strip().strip('"')
    elif line.startswith("psk="):
        psk = line.split("=", 1)[1].strip().strip('"')

if not ssid or not psk:
    raise SystemExit("Could not parse Wii U SSID/PSK")

conf.write_text(f"""interface={ap_if}
driver=nl80211
logger_stdout=-1
logger_stdout_level=0
ctrl_interface=/var/run/hostapd
hw_mode=a
channel={channel}
country_code=JP
ieee80211d=1
beacon_int=100
dtim_period=3
macaddr_acl=0
auth_algs=3
ap_max_inactivity=86400
skip_inactivity_poll=1
disassoc_low_ack=0
wmm_enabled=1
uapsd_advertisement_enabled=1
wmm_ac_be_acm=0
wmm_ac_be_aifs=2
wmm_ac_be_cwmin=4
wmm_ac_be_cwmax=5
wmm_ac_be_txop_limit=47
wmm_ac_bk_acm=0
wmm_ac_bk_aifs=7
wmm_ac_bk_cwmin=4
wmm_ac_bk_cwmax=10
wmm_ac_bk_txop_limit=0
wmm_ac_vi_acm=0
wmm_ac_vi_aifs=3
wmm_ac_vi_cwmin=4
wmm_ac_vi_cwmax=5
wmm_ac_vi_txop_limit=94
wmm_ac_vo_acm=0
wmm_ac_vo_aifs=3
wmm_ac_vo_cwmin=4
wmm_ac_vo_cwmax=5
wmm_ac_vo_txop_limit=47
ieee80211n=1
ssid={ssid}
ignore_broadcast_ssid=2
wpa=2
wpa_psk={psk}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
wpa_group_rekey=0
""")
conf.chmod(0o600)
PY

log "stopping old Wii U AP/stream processes"
killall -9 drcvncclient pad_probe 2>/dev/null || true
pkill hostapd 2>/dev/null || true
pkill dnsmasq 2>/dev/null || true
sleep 1

ip link set "${AP_IF}" down 2>/dev/null || true
iw dev "${AP_IF}" del 2>/dev/null || true
iw reg set JP 2>/dev/null || true
ensure_parent_sta
iw dev "${PHY_IF}" interface add "${AP_IF}" type __ap
if command -v nmcli >/dev/null 2>&1; then
  nmcli dev set "${AP_IF}" managed no >/dev/null 2>&1 || true
fi

rm -f "${HOSTAPD_LOG}" "${DNSMASQ_LOG}"
log "starting Wii U AP on ${AP_IF} channel ${CHANNEL}"
"${HOSTAPD}" -dd "${CONF}" > "${HOSTAPD_LOG}" 2>&1 &
echo $! > "${BASE}/hostapd.pid"

for _ in $(seq 1 120); do
  if grep -q "AP-ENABLED" "${HOSTAPD_LOG}" 2>/dev/null; then
    if grep -Eq "Beacon set failed|Failed to set beacon" "${HOSTAPD_LOG}" 2>/dev/null; then
      log "hostapd enabled but beacon setup failed"
      tail -n 80 "${HOSTAPD_LOG}" || true
      exit 1
    fi
    ip addr flush dev "${AP_IF}" 2>/dev/null || true
    ip addr add "${AP_IP}" dev "${AP_IF}"
    dnsmasq \
      --no-resolv \
      --port=0 \
      --interface="${AP_IF}" \
      --bind-interfaces \
      --dhcp-authoritative \
      --dhcp-range="${PAD_IP}","${PAD_IP}",255.255.255.0,12h \
      --log-dhcp \
      > "${DNSMASQ_LOG}" 2>&1 &
    echo $! > "${BASE}/dnsmasq.pid"
    log "AP ready; waiting for the GamePad is handled by the screen/start scripts"
    exit 0
  fi
  sleep 0.5
done

log "AP did not reach AP-ENABLED"
tail -n 120 "${HOSTAPD_LOG}" || true
exit 1
