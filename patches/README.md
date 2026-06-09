# Patch Registry

This directory contains patch stacks for the upstream projects used by the Wii U GamePad PC setup. See `../forks/manifest.json` and `../docs/third_party_forks.md` for the fork map.

## libdrc

- `libdrc_success_minimal.patch`: minimal libdrc runtime fixes required for the working setup.
- `libdrc_full_working_tree.patch`: fuller working-tree diff captured during bring-up.
- `0001-add-wii-u-gamepad-pc-success-fixes.patch`: git-format patch for the libdrc success fixes.
- `pad_probe_screen_demo.patch`: diagnostic screen/input demo changes.

## pc2drc / drcvncclient

- `0001-pc2drc-ubuntu24-wiiu-gamepad-vnc-success.patch`: git-format patch for the current drcvncclient success path.
- `pc2drc_drcvncclient_ubuntu24_success.patch`: direct drcvncclient diff.

## drc-hostap

There is no drc-hostap source patch in this directory yet. The current drc-hostap work lives in runtime integration scripts under `../scripts/`.
