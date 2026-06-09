# pc2drc drcvncclient Wii U GamePad PC Fork Stack

Upstream: local `pc2drc/libdrc-vnc/drcvncclient` snapshot used during bring-up. Pin the exact upstream URL before converting this branch into an independent GitHub repository.

This directory is intended to be split and published as:

```bash
git subtree split --prefix=forks/pc2drc-drcvncclient -b fork/pc2drc-drcvncclient-wiiu-gamepad-pc
git push origin fork/pc2drc-drcvncclient-wiiu-gamepad-pc
```

## Patch Series

Apply patches in the order listed in `series`.

The stack contains current-libdrc API compatibility, libswscale linkage, `864x480` row-by-row frame copying, and touch coordinate mapping.
