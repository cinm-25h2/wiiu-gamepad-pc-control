# Wii U GamePad PC Control

Web GUI and Ubuntu 24.04 helper scripts for using a Wii U GamePad as a PC display/input device through libdrc.

This repository is a practical wrapper around a working Ubuntu Live setup. It assumes libdrc, drc-hostap, pc2drc/drcvncclient, TigerVNC, and the Wii U DRC AP credentials have already been prepared on the host.

## Features

- Start and stop the Wii U DRC AP.
- Start and stop a `864x480` TigerVNC desktop stream to the GamePad.
- Toggle a watchdog that restarts the VNC stream if it drops.
- Switch to another GamePad already paired to the same Wii U credentials.
- Optional touch-coordinate debug logging.
- Experimental PC-hosted WPS pairing attempt for removing the Wii U console from the daily workflow.

## Security Notes

- The GUI creates a random token in `/root/wiiu-drc/gui-token`.
- The token value is not printed by `start_gui.sh` or the Python service.
- The top page and API both require `?token=<token>`.
- Task output is masked for common secret patterns such as `token=...`, `psk=...`, `wpa_psk=...`, `GH_TOKEN=...`, and `GITHUB_TOKEN=...`.
- Do not expose the GUI port to an untrusted network.
- Real AP credentials such as `get_psk.conf` are intentionally ignored by `.gitignore`.

If you need the token, read it locally on the Ubuntu host:

```bash
sudo cat /root/wiiu-drc/gui-token
```

## Install

On the Ubuntu host:

```bash
cd /root
git clone https://github.com/cinm-25h2/wiiu-gamepad-pc-control.git
cd /root/wiiu-gamepad-pc-control
sudo bash install.sh
```

Start the GUI:

```bash
sudo /root/wiiu-drc/start_gui.sh
```

The service listens on port `8765` by default. Open it from another machine using the Ubuntu host IP:

```text
http://<ubuntu-host-ip>:8765/?token=<token>
```

## GUI Controls

- `Stream Desktop ON`: start Openbox/LXPanel/PCManFM desktop mode on the GamePad.
- `Run Screen Test`: start the libdrc screen test profile.
- `AP ON`: restart only the Wii U DRC AP.
- `Stream OFF`: stop VNC and `drcvncclient`.
- `All OFF`: stop AP, VNC, and streaming.
- `Switch GamePad`: wait for another already-paired GamePad and save its MAC.
- `Watchdog ON/OFF`: enable or disable stream monitoring.
- `Touch Debug ON`: restart desktop mode with touch coordinate logs.
- `Experimental Direct Pair`: start a Wii U-like WPS pairing AP and show the symbol code to enter on the GamePad.

## CLI Scripts

The GUI calls the scripts installed under `/root/wiiu-drc/`:

```bash
/root/wiiu-drc/wiiu_gamepad_status.sh
/root/wiiu-drc/restart_wiiu_ap_keepalive.sh
START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
/root/wiiu-drc/run_wiiu_gamepad_screen_success.sh
/root/wiiu-drc/pair_or_switch_wiiu_gamepad.sh
/root/wiiu-drc/watch_drcvnc_success.sh
```

## Experimental Direct Pairing

There are two pairing paths:

1. Use a GamePad already paired with a Wii U console and reuse the console's DRC SSID/PSK.
2. Have the PC host a Wii U-like WPS pairing AP directly.

Path 1 is the known-good path. Path 2 is experimental. The old libdrc network documentation describes direct computer-hosted WPS pairing as future work, while the reverse-engineering notes indicate that it should work if the same WPS PIN digits are entered on both sides.

The experimental script:

- derives the Wii U identity from the current normal DRC SSID if possible,
- starts a pairing SSID ending in `_STA1`,
- accepts a 4-digit symbol code using digits `0..3`,
- sends WPS credentials for the normal AP,
- stores the associated GamePad MAC if pairing succeeds,
- switches back to the normal AP.

References:

- https://libdrc.org/docs/network.html
- https://libdrc.org/docs/re/wifi.html
- https://garyodernichts.github.io/drc_pin_generator/

## Included Patches

The `patches/` directory contains the working changes used during the Ubuntu 24.04 bring-up:

- libdrc TSF override/fallback support.
- libdrc UDP media source-port binding.
- Ubuntu 24.04 build fixes.
- `drcvncclient` compatibility fixes for the current libdrc API.
- `864x480` row-by-row VNC frame copy to fix diagonal distortion.
- `Streamer::SetTSArea` floating-point division fix for the touchscreen X axis.
- Touch mapping to the actual VNC client size.

## Known Good Runtime

```bash
LD_LIBRARY_PATH=/root/wiiu-drc/local/lib
DRC_GAMEPAD_IP=192.168.1.11
DRC_BIND_MEDIA_SOURCE_PORTS=1
DRC_TSF_BOOTTIME_OFFSET_US=<measured per AP run>
```

See `docs/quickstart_ubuntu24_wiiu_gamepad_pc.md` for the local quickstart notes.
