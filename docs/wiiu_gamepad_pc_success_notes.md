# Wii U GamePad PC Success Notes

## What Is Working

- Wii U GamePad associates to the PC AP on channel 48.
- Video reaches the GamePad.
- Diagonal video distortion is fixed by using `864x480` VNC and matching the libdrc stride.
- Touch X/Y coordinates now move across the full VNC surface after fixing `SetTSArea`.
- Lightweight desktop mode works with Openbox, LXPanel, PCManFM desktop, and xterm.

## Current Commands

```bash
/root/wiiu-drc/wiiu_gamepad_status.sh
START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
```

For touch debugging:

```bash
DRC_TOUCH_DEBUG=1 START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
tail -f /root/wiiu-drc/drcvncclient.log
```

## Touch Fix

The cursor edge-sticking came from libdrc's `Streamer::SetTSArea` doing integer division:

```cpp
static_cast<float>(target_w/kScreenWidth)
```

For `854/864`, this becomes `0` before being cast, breaking the calibration scale. The fixed version casts before division:

```cpp
static_cast<float>(target_w) / kScreenWidth
```

`drcvncclient` also now maps touch to `cl->width` and `cl->height`, clamps safely, and can log coordinates with `DRC_TOUCH_DEBUG=1`.

## Another GamePad

Run:

```bash
/root/wiiu-drc/pair_or_switch_wiiu_gamepad.sh
RESTART_AP=0 /root/wiiu-drc/run_wiiu_gamepad_screen_success.sh
START_DESKTOP=1 /root/wiiu-drc/start_drcvnc_success.sh
```

This handles a GamePad already paired to the same Wii U console credentials. A completely unpaired GamePad still needs Wii U console pairing first.
