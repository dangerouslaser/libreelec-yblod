# Validation

## R0.3.0

The final image was installed on i7-11390H. Native Kodi Player > Videos exposes
both preferences at Basic level; all values passed read/write checks. The
LibreELEC settings addon contains no DV helper or custom DV settings. Standard
DV Profile 7 FEL and Avatar Profile 8 playback supplied the release screenshots.
The final 31-patch series applies to fresh pinned sources with zero fuzz.

(0.3, historical: YBLOD 0.4.0 replaced this libplacebo HDR10 conversion with
the Vulkan engine's Master Reference conversion through the tunnel; see
OUTPUT-MODES.md. Its validation is 0.4.0 workstream C.)
The HDR10 conversion adds L1-guided libplacebo mapping. Sanitized software
tests cover metadata-driven output changes, unchanged native DV, FEL reference
agreement, target selection and output quantization. Kodi compilation passes.
Short real HDMI playback checks pass for Standard DV FEL, converted FEL, HDR10
and SDR. Calibrated visual fidelity and sustained hardware performance of this
new mapping have not been qualified. Earlier playback results below concern
the previous conversion path, not the new mapping.

The playback qualification below was run on the complete `0.3.0-dev4` image on
the i7-11390H test system.
No temporary player or skin overlay is required.

| Area | Evidence |
| --- | --- |
| Build and sources | Complete Linux/Kodi/LibreELEC image build passed. Source and canonical-license checks passed. The final release contains 31 patches; the LibreELEC Settings modification was removed. |
| Pixel preservation | Sanitized renderer tests passed for full/limited range and 1000, 2000, 4000 and 10000 nit PQ values without a 1000-nit mastering-metadata cap. |
| Conversion playback | P5, P8.1, P8.4, P10.1 and two P7 FEL samples passed HDMI signaling and presentation checks, including repeated Woman-at-80s seeks. |
| Output depth | The conversion pipe reports 30 bpp at 4K25 and 4K60. The 60 Hz case uses a retimed stress sample and the driver's validated deep-color format selection; it is not a full 60 fps profile-coverage claim. |
| Native behavior | SDR remains SDR under each preference. Disabled mode uses the native HDR10/HLG path. At 4K60, its previous 24-bpp behavior is retained rather than globally altered. |
| Preferences | Values persist across Kodi restart. A changed output mode does not alter an active session or a seek; it applies to the next playback. Native LibreELEC selection was exercised. |
| Information | Enhanced and stock panels open and close with the existing player actions. No Dolby logos or speaker diagram are added. |
| Render telemetry | Sanitized parser/delta tests cover duplicate clients, counter regression, capacity changes, missing data and sampling resets. Physical TV-Led and HDR10 FEL playback reports valid occupancy with unchanged drop/skip counters; properties stop refreshing when the panel closes. |
| Steady playback | Final-image P7 FEL CM4 runs measured 90 seconds per output mode with unchanged native drop/skip counters. Mean render-engine occupancy was 51.38% TV-Led and 51.99% HDR10; total CPU was 1.38% and 1.42%. These are sample-specific engine measurements, not total GPU power or N100 results. |
| Final restoration | No active player or failed service. The 4K60 desktop has DV signaling, conversion deep-color and HDR metadata cleared. Standard TV-Led defaults restored. |

The HDR10 path preserves reconstructed source values, including supported FEL
residuals. It does not claim proprietary target-display CM4 mapping or visual
equivalence to a licensed Dolby conversion engine. The framebuffer is currently
10-bit. The tested conversion output is
progressive 3840x2160. No additional N100 or legacy-TV qualification is claimed.

## R0.2.1a-opt1

Software checks and real HDMI playback are separate evidence. The qualified
image was installed on i7-11390H with a modern LG Standard-DV display. The public
image was then repackaged under the R0.2.1a-opt1 name; kernel and playback
binaries are unchanged. This naming-only package was not separately replayed.

| Area | Result |
| --- | --- |
| Software regression checks | 21 C/C++ checks with ASan/UBSan and 33 Python checks passed in the internal qualification suite. |
| HDMI packets and capabilities | Actual kernel packet pack/unpack checks and malformed-input tests passed; modern and legacy DV active-state guards checked. |
| Source reproducibility | All 29 patches apply without fuzz; 93 modified kernel/Kodi source files match the build after reconstructing stock LibreELEC plus this overlay. |
| Playback transitions | 19 software-state scenarios passed across SDR, HDR10, HLG, P5, P7 FEL, P8.1, P8.4 and P10, including direct file changes, pause/resume, seeks and return to SDR. Kodi did not restart. |
| Continuous playback | Two-minute P8.1 playback at 4K23.976 completed with no reported renderer presentation or stage failures; returned to the 4K60 SDR interface. These counters are not a measurement of every dropped/skipped frame. |
| Diagnostics | Automatic state changes and bounded summaries recorded; filtering, continuation through a busy kernel log and diagnostics-disabled transactions checked. |
| Packaging | Image dependency audit and complete-source inventory checks passed. Kernel and playback binaries match the qualified image; release identification files changed for the public name. |
| Native behavior | Original menus retained. SDR/HDR10/HLG sources use Kodi's native path, with HDMI-DV disabled. |

The internal build/test harnesses and lab reports are not distributed in this
repository. Reproducible image build scripts, pinned sources, patches, licenses
and corresponding sources remain available.

## Rendering evidence retained

The unchanged optimized renderer was previously checked against its separate
full-precision path on twelve deterministic 4K cases and six real-frame sources.
Lanczos sampling checks compared 288 FP32 cases, including fallback conditions.
FEL seek checks compared 2,876 reference enhancement pictures and repeated seeks;
successful physical runs verified picture order and continued playback.

CM2.9/CM4 transport and the tested profile paths remain unchanged by this release.
Startup and user-interaction disturbances are evaluated separately from steady
playback. A DV logo alone never proves correct image reconstruction or metadata.

## Limits

- No physical v0/v1 sink or the reported 12400T/matrix route was available for
  this qualification. Their capability/signaling code is tested in software,
  not certified across all receivers, switches or televisions.
- No new N100 performance measurement was made.
- P7 MEL and P8.2 do not have dedicated physical LibreELEC qualification here.
  P9 is not supported by the pinned H.264 metadata path; P10 evidence does not
  qualify every compatibility variant or refresh rate.
- Software display-state checks are not an external HDMI capture, visual
  certification or a guarantee of zero dropped frames.
- Diagnostics are deliberately bounded. Unavailable or truncated kernel
  evidence is reported where detectable; this is not a full system journal.

## Source checks

On Linux with Python 3.12 or newer:

```sh
python3 tools/verify.py
python3 tools/check-patches.py --source-cache /path/to/LibreELEC-DV/sources \
  --output /path/to/new-source-check
```

These checks verify source inputs, license records and patch application, not
physical HDMI playback. See [BUILD.md](BUILD.md) to reproduce the image.
# Format-aware information panel

The adaptive panel was exercised with SDR, HDR10, HLG, Standard Dolby Vision and Dolby Vision converted to HDR10. Native formats select the compact panel; both DV paths retain source metadata. Missing metadata rows are hidden. HDR10 static mastering and content-light values were verified against the source. This UI change does not modify video processing or output selection.

# NUC7i7BN: Dolby Vision through the MegaChips MCDP2800 LSPCON

PCON mode (below): not possible. Level-shifter mode (0.3.5, next section):
Dolby Vision works.

Tested 2026-11-08 by a volunteer: NUC7i7BNB (Kaby Lake GT3, BIOS 0093), MCDP2800
HW 2.2 FW 1.77 on port B (connector DP-1), direct HDMI to an LG OLED55C3 whose
EDID parses as Standard DV v2. Image: NUC Display Lab v0.2.0-dvlab (the 0.3.3
Linux 7.3 kernel plus a lab-only i915 patch; dangerouslaser/nuc-hardware-lab
`image/dvlab`), report #8 in nuclab-reports. 3840x2160 23.976 Hz, RGB8 full range.

| Step | Signalling | TV | DP RX CRC |
|---|---|---|---|
| C1 | DV-style AVI (RGB, full, VIC 93) via the MCA mailbox | normal picture, 8/8 near-black and 8/8 near-white steps | matches framebuffer |
| C2 | HDR10: DRM InfoFrame as a DP InfoFrame SDP in the GMP DIP (`00 87 1d 4c`) | HDR logo | matches |
| H1 | Dolby VSIF as a DP InfoFrame SDP in the VS DIP (`00 81 1d 4c 01 1b 46 d0 00 02`) | no DV; raw tunnel (green/purple) | matches |
| H1b | as H1 with HB2 = 0x1c | no DV | matches |
| H2 | the H1 packet in the GMP DIP (the slot C2 proves is forwarded) | no DV | matches |
| Negative | H1 with every tunnel metadata CRC broken | no DV | matches |
| C1 again | DV-style AVI | normal picture | matches |

Readback confirmed the exact DIP bytes and enables in every step, and the
firmware acknowledged every AVI write. The pixel bytes reach the converter
unchanged (the sink CRC equals the framebuffer CRC, also for the tunnel frame),
so the failure is the vendor InfoFrame: FW 1.77 converts the GMP SDP when it
carries type 0x87 and drops it with type 0x81, and does not forward the VS DIP.
The vendor DPCD range 0x5B0-0x5FF NAKs reads; no other mailbox is known, and
none is written by guesswork (a stray AUX write can brick the converter).

Result: no Dolby Vision route on this converter firmware. The DV property is
not exposed on LSPCON connectors; these NUCs fall back to the Dolby Vision to
HDR10 conversion. Its HDR10 signalling through the converter is confirmed (C2);
conversion playback on Kaby Lake was not qualified. Recognition failed, so transport, lifecycle and playback were not
qualified. The unmerged driver work is kept on branch `feature/nuc7-lspcon-dv`
(`linux-9930-lspcon-mca-dv`) in case another firmware or a documented mechanism
turns up.

# NUC7i7BN: Dolby Vision through the MCDP2800 in level-shifter mode (0.3.5)

Tested 2026-11-09 by the same volunteer and NUC7 + LG OLED55C3, NUC Display Lab
v0.3.1-dvlab and v0.4.0-dvlab (reports #15 and #17 in nuclab-reports; the
0.3.3 Linux 7.3 kernel plus a lab-only i915 patch). The lab put the MCDP2800 in
level-shifter mode through the standard dual-mode register (I2C 0x40, offset
0x40, over AUX; read back `00` in level-shifter mode, `01` in PCON mode) and
re-probed i915, so the port appeared as HDMI-A-1 driven by the GPU's own
native-HDMI DV path. EDID through the LSPCON's I2C-over-AUX bridge.
3840x2160 23.976 Hz RGB8 full range (296.7 MHz TMDS).

| Step (report #17) | Frame | Dolby VSIF | TV |
|---|---|---|---|
| Levels | steps pattern | no | 8/8 near-black, 8/8 near-white |
| No VSIF | DV reference | no | no DV, raw tunnel (green/purple) |
| DV-A | DV reference | yes | Dolby Vision, correct test picture |
| DV-B | same picture, RPU L1 max 4095 / avg 3600 | yes | Dolby Vision, darker than DV-A |
| DV-A again | DV reference | yes | Dolby Vision, brighter again |
| Broken metadata | every tunnel metadata CRC broken | yes | Dolby Vision, test picture (the C3 does not reject it) |

The DV reference and DV-B frames differ only in the 87 metadata pixels of
row 0, so the brightness change shows the TV uses the transported metadata.
Report #15 gave the same DV result. Switching back to PCON mode retrained the
DP link (HBR2 x4) and restored the normal picture in both runs.

Qualified: recognition, pixel and metadata transport (volunteer's visual
comparison, not a measurement). Not qualified: the in-modeset mode switch of
`linux-9931` (the lab re-probed i915 instead), TV off/on and suspend/resume
during DV, and Kodi playback on Kaby Lake GT3. Limits: 4K up to 30 Hz (the
MCDP28x0 datasheet's 340 Mchar/s level-shifter limit, gen9 HDMI 300 MHz); no
HDR10 tunnel format in level-shifter mode (gen9 has no DRM InfoFrame DIP).

# INUC 11i5FL: Dolby Vision through an onboard DP-to-HDMI converter (0.3.4)

Tested 2026-11-08 by a volunteer: INUSUAL INUC 11i5FL (Tiger Lake, board
CM11EBV58W). Both HDMI sockets are DP outputs (DP-1 = port B, DP-2 = port E)
behind identical onboard DP-to-HDMI protocol converters with a blank branch ID
(DFP `0b f0 02 00`); there is no native HDMI. Direct HDMI to a Sony Bravia 7
(Standard DV, VSVDB v2, interface 2).

Lab (NUC Display Lab v0.3.0-dvlab, report #13; the same kernel with a lab
patch), 3840x2160, RGB8 full range, the DV AVI as a DP InfoFrame SDP in the
AVI DIP:

| Step | Dolby VSIF | TV |
|---|---|---|
| C1 | none (DV AVI only) | no logo; level steps not sure |
| C2 | HDR10 DRM InfoFrame SDP in the GMP DIP | HDR logo, 8/8 near-black steps |
| H1, H1b | DP InfoFrame SDP in the VS DIP (HB2 0x1d / 0x1c) | black / no signal |
| H2 | the same SDP in the GMP DIP | Dolby Vision logo, correct colour bars, at 4K23.976 and 4K59.94 |
| Negative | H2 with every tunnel metadata CRC broken | Dolby Vision logo, colour bars |
| C1 again | DV AVI only | no logo, 8/8 near-black and 8/8 near-white steps |

The Sony accepted the broken-CRC frame, so on this TV the logo alone does not
prove that the metadata arrives intact; the correct picture of the valid
frame does show the tunnel decoded. The converter has no sink CRC.

`linux-9930-dp-pcon-dv` implements H2 for the product: on DP ports where it is
allowed, the connector gets DVBRIDGE_DV_STANDARD_LAB; at modeset the route must
be a DP branch with an HDMI DFP and an HDMI sink, and the usual link policy
applies (RGB8, full range, CTA timing, no HDR blob), with the downstream TMDS
limit always respected. Readout maps the SDPs back for the state checker.

Playback: the volunteer played Dolby Vision titles in Kodi on test image
0.3.4-test1 (0.3.3 plus `linux-9930` only) and confirmed Dolby Vision on the
TV. 0.3.4 adds linux-9928 (DVBRIDGE_TUNNEL_FORMAT, default dolby-vision, HDMI
connectors only) and the engine's HDR10 code (unused); the converter route was
not re-tested on the release image.

Not qualified: other converters (`i915.dv_pcon=1` is experimental), the
through-soundbar route, and Dolby Vision to HDR10 on DP (not offered).
