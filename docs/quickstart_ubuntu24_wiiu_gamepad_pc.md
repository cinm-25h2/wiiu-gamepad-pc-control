# Quickstart: Wii U GamePad on Ubuntu 24.04

## Current Working State

- AP interface: `ap0`
- PC/AP IP: `192.168.1.10/24`
- GamePad IP: `192.168.1.11`
- Channel: `48` / `5240 MHz`
- VNC display: `Xtigervnc :1`
- VNC geometry: `864x480`
- Streamer: `drcvncclient :1`

## Status Check

```bash
/root/wiiu-drc/wiiu_gamepad_status.sh
```

## Start GamePad Screen Test

Restart the AP, measure TSF, and run the libdrc test app:

```bash
/root/wiiu-drc/run_wiiu_gamepad_screen_success.sh
```

Keep the current AP running and only re-measure/restart the stream:

```bash
RESTART_AP=0 /root/wiiu-drc/run_wiiu_gamepad_screen_success.sh
```

`PAD_MAC` is now optional. If it is not set, the script waits for the first associated GamePad and stores it in `/root/wiiu-drc/gamepad_mac.conf`.

## Show a PC Desktop on the GamePad

Start the VNC desktop stream:

```bash
START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
```

Useful options:

```bash
START_XEV=1 START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
DRC_TOUCH_DEBUG=1 START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
OPEN_FILE_MANAGER=1 START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
```

## Switch to Another GamePad

This works for another GamePad that is already paired with the same Wii U console credentials.

```bash
/root/wiiu-drc/pair_or_switch_wiiu_gamepad.sh
RESTART_AP=0 /root/wiiu-drc/run_wiiu_gamepad_screen_success.sh
START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
```

If the GamePad is completely unpaired, pair it with the Wii U console first. This PC setup impersonates the Wii U DRC AP using the console SSID/PSK; an unpaired GamePad will not know those credentials yet.

## Important Runtime Environment

```bash
LD_LIBRARY_PATH=/root/wiiu-drc/local/lib
DRC_GAMEPAD_IP=192.168.1.11
DRC_BIND_MEDIA_SOURCE_PORTS=1
DRC_TSF_BOOTTIME_OFFSET_US=<measured per AP run>
```

On Intel concurrent STA/AP runs, the measured TSF offset can be negative. Use the included signed-offset libdrc patch before relying on that value.

## Key Fixes

- Intel AX201 works here by keeping STA+AP concurrent on the same 5 GHz channel.
- VNC is `864x480`, matching libdrc's internal screen stride.
- `drcvncclient` copies VNC frames row-by-row into an `864x480` send buffer, fixing diagonal distortion.
- `libdrc::Streamer::SetTSArea` now uses floating-point division, fixing the touchscreen X axis sticking at an edge.
- `drcvncclient` maps touch coordinates to the actual VNC client size and has optional `DRC_TOUCH_DEBUG=1` logging.

## Patch Files

- `0001-add-wii-u-gamepad-pc-success-fixes.patch`: libdrc fixes.
- `0001-pc2drc-ubuntu24-wiiu-gamepad-vnc-success.patch`: pc2drc/drcvncclient fixes.
- `pc2drc_drcvncclient_ubuntu24_success.patch`: direct drcvncclient diff.
