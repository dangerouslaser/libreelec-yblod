# Hardware requirements

The tested LE platform is an Intel Core i7-11390H Geekom IT11 / Iris Xe system, connected
through native HDMI to an LG G5. Results apply to that route, not every mini-PC
sold with the same CPU.

## Conditions for automatic DV output

1. Intel display engine generation 12 or later, handled by the patched display
   driver; the CPU marketing generation alone is not sufficient. Exceptions:
   the converter routes in condition 2 (gen11+, and the NUC7's gen9 LSPCON).
2. Native HDMI, without active DisplayPort/LSPCON conversion. A native HDMI
   level shifter is not rejected merely for exposing a dual-mode identifier.
   In its normal (PCON) mode the NUC7i7BN's MegaChips MCDP2800 LSPCON (FW
   1.77) does not forward the Dolby VSIF (see VALIDATION.md). Exception (0.3.5,
   `linux-9931-lspcon-ls-dv`): for Dolby Vision the driver switches it to
   level-shifter mode and drives the port as HDMI, so the native-HDMI DV
   signalling reaches the TV; DV off switches it back. DV is 4K up to 30 Hz
   there (level-shifter and gen9 HDMI clock limits), so Kodi's refresh-rate
   switching must be on. On by default only for allowlisted boards (DMI board
   NUC7i7BNB) with an MC2800 on FW 1.77; `i915.dv_lspcon=1` for other gen9/10
   LSPCON boards (experimental), `i915.dv_lspcon=0` turns it off. Other
   LSPCONs (Parade) stay excluded: Dolby Vision titles play as Kodi's plain
   base layer there (0.3's GL conversion to HDR10 is gone in 0.4.0).
   Exception (0.3.4, `linux-9930-dp-pcon-dv`): gen11+ boards whose HDMI
   sockets are an onboard DP-to-HDMI protocol converter (not LSPCON). The
   Dolby VSIF goes to the converter as a DP InfoFrame SDP in the GMP DIP, as
   HDR10 does. On by default only for allowlisted boards (DMI): the INUSUAL
   INUC 11i5FL (board CM11EBV58W), verified (see VALIDATION.md). Other boards:
   `i915.dv_pcon=1`, experimental. `i915.dv_pcon=0` turns it off. Kodi's
   "Convert to HDR10" output mode is not offered on these DP ports, nor on
   the LSPCON route above (Dolby Vision only, plan decision 3).
3. A valid Dolby EDID v0, v1 or v2 block advertising Standard DV. Both Kodi and
   the driver use the same validation. V0 and applicable v1 sinks use legacy
   Standard-DV HDMI signaling; modern sinks retain the Dolby-OUI packet.
   LLDV-only, malformed and unsupported-version blocks remain ineligible.
   The newly added v0/v1 routes have software coverage, not physical qualification.
4. A supported progressive 3840 × 2160 display mode in Kodi, atomic GBM/GLES
   output and the required texture/rendering precision.
5. Hardware decoding and import of the actual stream format. FEL additionally
   requires enhancement-layer decoding and matched surfaces.
6. A Vulkan device for the display's GPU (Mesa ANV on Intel, RADV on AMD):
   since 0.4.0 the Vulkan engine is the only Dolby Vision renderer. Without
   one, Dolby Vision titles play as plain base-layer video, with one
   notification per Kodi run (OUTPUT-MODES.md).

## Conditions for HDR10 output (Convert to HDR10)

An HDR10 display (EDID) on a native HDMI connector whose driver exposes
`DVBRIDGE_TUNNEL_FORMAT` with `hdr10` (linux-9928: Intel display gen12 and
later, amdgpu), progressive 3840 × 2160, and the Vulkan engine with HDR10
output. A Dolby Vision EDID is not needed. Not on the converter routes
(condition 2).

## Conditions for HDR10+ output (Convert to HDR10+)

Everything Convert to HDR10 needs, plus: the connector's `HDR10PLUS_METADATA`
property (linux-9932: i915 HDMI connectors on display version 10 and later
and amdgpu HDMI-A connectors; never the DP connectors of the converter
routes), an HDR10+ Vendor-Specific Video Data Block in the TV's EDID (Kodi
reads its application version and sends packets of that version), and the
Vulkan engine with HDR10+ output. LG TVs have no HDR10+; Samsung, and
Panasonic/Philips models with HDR10+, do. Untested on hardware so far.

## HDR10+ videos as Dolby Vision

The Dolby Vision output's conditions above (a Standard Dolby Vision TV,
3840 × 2160, hardware decoding through VAAPI), an engine with
`dvvk_hdr10plus_to_dovi`, and an HDR10+ video with one processing window per
picture. No HDR10+ support is needed in the TV.

The driver policy accepts CTA 24/25/30/50/60 Hz timings and their fractional
variants, including 23.976 Hz. Acceptance is not a performance certification at
every rate. Kodi's renderer currently uses a 4K transport raster; a lower
resolution source does not make this a qualified 1080p-output implementation.

## Performance reporting

Report the exact CPU, PCI/display driver, HDMI route, TV, source profile/codec,
resolution/rate, visible subtitles.

GPU engine-busy percentages are not additive and are not power measurements.
Dynamic GPU clocks can reduce power/work without producing a proportional
change in a single utilization number. Do not compare them directly to Android
decoder-chip utilization.

N100/N150 and other small iGPUs are candidates for validation and optimization,
not advertised as guaranteed real-time FEL/4K60 devices. No CPU offload is used
as a substitute for the GPU reconstruction path.
