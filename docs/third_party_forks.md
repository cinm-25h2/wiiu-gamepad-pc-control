# Third-Party Fork Map

This project is intentionally split into a small control wrapper plus patch stacks for the upstream projects it depends on. Use `forks/manifest.json` as the machine-readable source of truth.

## Branch Naming

When publishing fork snapshots into this GitHub repository, use these branches:

- `main`: web GUI, orchestration scripts, docs, and patch registry.
- `fork/libdrc-wiiu-gamepad-pc`: libdrc patch stack for Ubuntu 24.04, TSF, UDP ports, touch, and diagnostics.
- `fork/pc2drc-drcvncclient-wiiu-gamepad-pc`: pc2drc/drcvncclient patch stack for VNC streaming.
- `fork/drc-hostap-wiiu-gamepad-pc`: drc-hostap runtime integration notes and AP/WPS scripts.

If separate GitHub repositories are created later, keep the same suffixes so the relationship remains obvious:

- `wiiu-gamepad-pc-control`
- `wiiu-gamepad-pc-libdrc`
- `wiiu-gamepad-pc-pc2drc-drcvncclient`
- `wiiu-gamepad-pc-drc-hostap`

## Components

### libdrc

Upstream: `https://bitbucket.org/memahaxx/libdrc`

Patch files:

- `patches/libdrc_success_minimal.patch`
- `patches/libdrc_full_working_tree.patch`
- `patches/0001-add-wii-u-gamepad-pc-success-fixes.patch`
- `patches/pad_probe_screen_demo.patch`

What this fork carries:

- Ubuntu 24.04 build fixes.
- Signed `DRC_TSF_BOOTTIME_OFFSET_US` handling for Intel concurrent STA/AP runs.
- TSF fallback options.
- UDP media source-port binding.
- Touch X-axis fix in `Streamer::SetTSArea`.
- `pad_probe` diagnostics used during GamePad bring-up.

### pc2drc / drcvncclient

Upstream: currently tracked as the local `pc2drc/libdrc-vnc/drcvncclient` snapshot used during bring-up. The exact upstream URL still needs to be pinned if this becomes a standalone GitHub fork.

Patch files:

- `patches/0001-pc2drc-ubuntu24-wiiu-gamepad-vnc-success.patch`
- `patches/pc2drc_drcvncclient_ubuntu24_success.patch`

What this fork carries:

- Current libdrc API compatibility.
- `libswscale` link fix.
- `864x480` row-by-row frame copy to remove diagonal distortion.
- Touch coordinate mapping to the VNC client's actual size.

### drc-hostap

Upstream: `https://bitbucket.org/memahaxx/drc-hostap`

This repository does not currently carry a source patch for drc-hostap. It carries runtime integration scripts that use the built hostapd/netboot tools:

- `scripts/restart_wiiu_ap_keepalive.sh`
- `scripts/pair_or_switch_wiiu_gamepad.sh`
- `scripts/pair_gamepad_pc_wps_experimental.sh`

What this integration carries:

- Wii U DRC AP configuration generated from the local `get_psk.conf`.
- Intel LAR/IR-concurrent guardrails by reconnecting a parent STA before starting the 5 GHz AP.
- Experimental PC-hosted WPS pairing AP.

## Secrets Boundary

Do not commit runtime credentials or machine-local state. In particular, keep these out of every fork branch and repository:

- `get_psk.conf`
- `gui-token`
- `sta_parent.conf`
- SSH keys
- hostapd/dnsmasq logs containing real association state
