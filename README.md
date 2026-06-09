# drc-hostap Wii U GamePad PC Integration Stack

Upstream: `https://bitbucket.org/memahaxx/drc-hostap`

This directory is intended to be split and published as:

```bash
git subtree split --prefix=forks/drc-hostap -b fork/drc-hostap-wiiu-gamepad-pc
git push origin fork/drc-hostap-wiiu-gamepad-pc
```

This is not a drc-hostap source patch stack yet. It contains the runtime scripts that drive the built hostapd/netboot tools for this setup:

- normal Wii U DRC AP restart from local credentials,
- Intel LAR/IR-concurrent AP guardrails,
- already-paired GamePad switching,
- experimental PC-hosted WPS pairing.
