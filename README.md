# libdrc Wii U GamePad PC Fork Stack

Upstream: `https://bitbucket.org/memahaxx/libdrc`

This directory is intended to be split and published as:

```bash
git subtree split --prefix=forks/libdrc -b fork/libdrc-wiiu-gamepad-pc
git push origin fork/libdrc-wiiu-gamepad-pc
```

## Patch Series

Apply patches in the order listed in `series`.

The stack contains Ubuntu 24.04 build fixes, signed TSF offset handling, UDP media source-port binding, touch fixes, and `pad_probe` diagnostics.
