#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/root/wiiu-drc}"
AP_IF="${AP_IF:-ap0}"
PHY_IF="${PHY_IF:-wlp0s20f3}"
CHANNEL="${CHANNEL:-48}"
AP_IP="${AP_IP:-192.168.1.10/24}"
PAD_IP="${PAD_IP:-192.168.1.11}"
WPS4="${WPS4:-0000}"
PAIR_TIMEOUT="${PAIR_TIMEOUT:-180}"
HOSTAPD="${HOSTAPD:-${BASE}/third_party/drc-hostap/hostapd/hostapd}"
HOSTAPD_CLI="${HOSTAPD_CLI:-${BASE}/third_party/drc-hostap/hostapd/hostapd_cli}"
NETBOOT="${NETBOOT:-${BASE}/third_party/drc-hostap/netboot/netboot}"
CONF="${BASE}/wiiu_ap_pc_pairing.conf"

log() {
  printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

if [[ ! "${WPS4}" =~ ^[0-3]{4}$ ]]; then
  fail "WPS4 must be four digits using only 0,1,2,3"
fi

python_values="$(
python3 - <<'PY'
from pathlib import Path
import os
import secrets

base = Path(os.environ.get("BASE", "/root/wiiu-drc"))
ssid = psk = None
cfg = base / "get_psk.conf"
if cfg.exists():
    for line in cfg.read_text().splitlines():
        line = line.strip()
        if line.startswith("ssid="):
            ssid = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("psk="):
            psk = line.split("=", 1)[1].strip().strip('"')

identity = os.environ.get("PAIR_ID_HEX", "")
if not identity and ssid and ssid.startswith("WiiU"):
    identity = ssid[4:]
identity = "".join(ch for ch in identity.lower() if ch in "0123456789abcdef")
if len(identity) != 12:
    raise SystemExit("Could not derive 12-hex Wii U identity. Set PAIR_ID_HEX.")

if not psk:
    psk = secrets.token_hex(32)

first = identity[:-2] + f"{(int(identity[-2:], 16) + 7) & 0xff:02x}"
normal_ssid = os.environ.get("NORMAL_SSID", f"WiiU{identity}")
pair_ssid = os.environ.get("PAIR_SSID", f"WiiU{first}{identity}_STA1")
print(f"IDENTITY={identity}")
print(f"NORMAL_SSID={normal_ssid}")
print(f"NORMAL_PSK={psk}")
print(f"PAIR_SSID={pair_ssid}")
PY
)"
eval "${python_values}"
PIN="${WPS4}5678"

log "experimental PC-hosted pairing"
log "pairing SSID: ${PAIR_SSID}"
log "normal SSID: ${NORMAL_SSID}"
log "WPS digits: ${WPS4} -> PIN ${PIN}"
log "enter the displayed symbols on the GamePad"

killall -9 drcvncclient pad_probe hostapd dnsmasq 2>/dev/null || true
vncserver -kill :1 >/dev/null 2>&1 || true
ip link set "${AP_IF}" down 2>/dev/null || true
iw dev "${AP_IF}" del 2>/dev/null || true
iw dev "${PHY_IF}" interface add "${AP_IF}" type __ap 2>/dev/null || true
ip link set "${AP_IF}" up
ip addr flush dev "${AP_IF}" 2>/dev/null || true
ip addr add "${AP_IP}" dev "${AP_IF}"

cat > "${CONF}" <<EOF_CONF
interface=${AP_IF}
driver=nl80211
logger_stdout=-1
logger_stdout_level=0
ctrl_interface=/var/run/hostapd
hw_mode=a
channel=${CHANNEL}
country_code=JP
ieee80211d=1
beacon_int=100
dtim_period=3
macaddr_acl=0
auth_algs=3
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
ssid=${PAIR_SSID}
ieee8021x=1
eapol_version=1
eap_server=1
wps_pin_requests=/tmp/wiiu-hostapd-pinreq
wps_state=2
uuid=22210203-0405-0607-0809-0a0b0c0d0e0f
manufacturer=Broadcom
model_name=SoftAP
model_number=0
serial_number=0
device_type=6-a4c0e1f4-1
device_name=WiiU${IDENTITY}
os_version=80000000
config_methods=label push_button
EOF_CONF

rm -f "${BASE}/hostapd_pairing.log"
"${HOSTAPD}" -dd "${CONF}" > "${BASE}/hostapd_pairing.log" 2>&1 &
echo $! > "${BASE}/hostapd_pairing.pid"

for _ in $(seq 1 80); do
  if grep -q "AP-ENABLED" "${BASE}/hostapd_pairing.log" 2>/dev/null; then
    break
  fi
  sleep 0.5
done
grep -q "AP-ENABLED" "${BASE}/hostapd_pairing.log" ||
  fail "pairing AP did not start"

"${HOSTAPD_CLI}" -i "${AP_IF}" wps_config "${NORMAL_SSID}" WPA2PSK CCMP "${NORMAL_PSK}" || true
"${HOSTAPD_CLI}" -i "${AP_IF}" wps_pin any "${PIN}" "${PAIR_TIMEOUT}" || true

log "waiting for WPS success or GamePad association"
paired_mac=""
deadline=$((SECONDS + PAIR_TIMEOUT))
while (( SECONDS < deadline )); do
  if grep -q "WPS-SUCCESS\\|WPS:.*success\\|WPA: pairwise key handshake completed" "${BASE}/hostapd_pairing.log" 2>/dev/null; then
    paired_mac="$(iw dev "${AP_IF}" station dump 2>/dev/null | awk '/^Station / { print $2; exit }')"
    break
  fi
  paired_mac="$(iw dev "${AP_IF}" station dump 2>/dev/null | awk '/^Station / { print $2; exit }')"
  if [[ -n "${paired_mac}" ]] && grep -q "WPS" "${BASE}/hostapd_pairing.log" 2>/dev/null; then
    break
  fi
  sleep 1
done

tail -n 80 "${BASE}/hostapd_pairing.log" || true

if [[ -z "${paired_mac}" ]]; then
  fail "no GamePad associated during pairing window"
fi

cat > "${BASE}/get_psk.conf" <<EOF_PSK
ssid="${NORMAL_SSID}"
psk=${NORMAL_PSK}
EOF_PSK
printf '%s\n' "${paired_mac}" > "${BASE}/gamepad_mac.conf"
log "stored GamePad MAC ${paired_mac}"

log "switching to normal Wii U AP"
"${BASE}/restart_wiiu_ap_keepalive.sh"

if [[ -x "${NETBOOT}" ]]; then
  timeout 25 "${NETBOOT}" 192.168.1.255 192.168.1.10 "${PAD_IP}" "${paired_mac}" || true
fi

log "direct pairing attempt complete"
log "start desktop with: START_DESKTOP=1 ${BASE}/start_drcvnc_success.sh"
