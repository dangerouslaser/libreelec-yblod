# Kernel parameters of the YBLOD patches

The switches the fork's kernel patches add (`yblod-engine/patches/linux`,
`yblod/patches/linux`), their defaults, and how to set them.

## Which driver name

The Intel display code is built into two drivers, and a parameter carries the
name of the driver that runs the display:

- `i915.<name>` on Intel graphics up to Meteor Lake and Arrow Lake (the i915
  driver; built into the kernel);
- `xe.<name>` on Lunar Lake, Battlemage (Arc B-series) and Panther Lake (the
  xe driver; a module). `i915.qms=0` does nothing there: write `xe.qms=0`.

`cat /sys/class/drm/card*/device/uevent | grep DRIVER` shows which one it is.
AMD graphics use `amdgpu.<name>` (built in).

Each parameter is one switch for every display of that driver, not one per
connector.

## How to set one

- At boot: add `i915.qms=0` (for example) to the kernel command line, the
  `APPEND` line of `/flash/syslinux.cfg` (and the `linux` line of
  `/flash/EFI/BOOT/grub.cfg`, which 32-bit UEFI firmware uses). `/flash` is
  read-only: `mount -o remount,rw /flash` first.
- While running, the parameters marked "runtime" below:
  `echo 0 > /sys/module/i915/parameters/qms`. They take effect at the next
  mode change (or the next hotplug, for the HPD ones) and are back at their
  defaults after a reboot.

## Intel (`i915.` or `xe.`)

| Parameter | Default | Runtime | What it does |
|---|---|---|---|
| `enable_dv_lab` | on | no | The Dolby Vision tunnel: the `DVBRIDGE_DV_STANDARD_LAB` and `DVBRIDGE_TUNNEL_FORMAT` connector properties on native HDMI (display version 12 and later) and on the two converter routes below. `0` removes them; Kodi then plays Dolby Vision titles without Dolby Vision output. |
| `dv_pcon` | -1 | no | Dolby Vision through an onboard DP-to-HDMI converter, display version 11 and later. `-1` verified boards only (INUSUAL INUC 11i5FL, board CM11EBV58W), `0` off, `1` any such converter (experimental: an untested converter may show no picture). |
| `dv_lspcon` | -1 | no | Dolby Vision through a MegaChips MCDP2800 LSPCON switched to level-shifter mode, display version 9/10, 4K up to 30 Hz. `-1` verified boards only (Intel NUC7i7BNB), `0` off, `1` any board with that chip (the firmware version is checked in both cases). |
| `qms` | on | yes | HDMI 2.1 Quick Media Switching: refresh rate changes at 1080p and 2160p without a blank, on TVs whose EDID has the QMS bit. Display version 12 to 29 only (Tiger Lake to Lunar Lake; it has run on Tiger Lake and Alder Lake-N); on other hardware the parameter does nothing. `0` gives ordinary mode changes. |
| `hdmi_freesync` | 0 | yes | Not yet run on hardware, so off by default. FreeSync over HDMI on TVs with a FreeSync range that reaches 60 Hz, where QMS is possible. `0` off, `1` while the CRTC's `VRR_ENABLED` is set, `2` also without it. Modes and `vrr_capable` change at the next probe of the connector. |
| `spd_sdi` | 1 | yes | Source type in the SPD InfoFrame: `1` Digital STB (so TVs don't treat the input as a PC), `9` PC general (upstream's value); any CTA-861 code 0 to 13. |
| `hdr_yuv420` | on | yes | HDR (PQ or HLG metadata, max bpc 10 or more) at 4K50/60: 10 bpc YCbCr 4:2:0 where 10 bpc RGB doesn't fit HDMI 2.0, not 8 bpc RGB. `0` is upstream's choice. Never applies to the Dolby Vision tunnel. |
| `hpd_hold_ms` | 3000 | yes | Milliseconds an HDMI sink with an active output is still reported as connected after HPD goes low (TVs drop it briefly when they change picture mode). A real unplug is reported after that time. `0` off. Display version 11 and later. |

## AMD (`amdgpu.`)

| Parameter | Default | Runtime | What it does |
|---|---|---|---|
| `enable_dv_lab` | on | no | The Dolby Vision tunnel on native HDMI, DCN 1.0 to 3.6: the same two connector properties. `0` removes them. |
| `hdr_yuv420` | on | yes | As on Intel, for the "color format" AUTO setting. |
| `hdmi_hpd_debounce_delay_ms` | 3000 | yes | Upstream's HDMI HPD debounce, which upstream leaves off (0). A sink that comes back within the time with the same EDID causes no hotplug event. |

Not parameters, and always on: after a hotplug of a connected HDMI sink i915
looks at the sink's SCDC TMDS configuration again once a second for 4 s and
makes a modeset if it does not match the link (at most 3 in 20 s).
