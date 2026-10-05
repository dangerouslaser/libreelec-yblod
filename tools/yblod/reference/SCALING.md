# Enhancement-layer scaling: reference and hardware boundary

This checkpoint checks our scaler independently of SK4 pictures. It does not
change preparation defaults or establish a licensed Dolby implementation.

## Public specification boundary

[ETSI GS CCM 001 V1.1.1](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf)
clause 4 places resampling outside normative composition, assuming it happens
before composition. Clause 5.2.2 requires matching resolution, luma phase and
chroma position at composer inputs. Annex B, page37, is an **informative example**,
not a filter requirement for all Dolby players. It specifies vertical then
horizontal passes, replicated edges, per-pass rounding and unsigned16 bounds.

[Dolby's public Profile 7 notes](https://ott.dolby.com/OnDelKits/Dolby_Vision_Online_Delivery_Kit/v1/Documentation/Specs/Visio_Profiles/help_files/topics/c_notes_profile_public.html)
require aligned layers and top-left chroma in both encoded layers. They do not
establish the exact half-resolution-to-full-resolution scaler inside SK4.
ETSI CCM is useful public mathematics, not Dolby certification.

Our baseline enlarges decoded EL codes before converting them into signed
enhancement corrections. Alternative ordering remains a labelled diagnostic,
not an equally established interpretation of this public reference process.

## Coordinate audit and independent tests

In supplied-plane coordinates, Annex-B filters reproduce interior affine ramps
at horizontal `x/2` and vertical `y/2-1/4`. Under that example's declared
registration, native EL luma `(x,u)` corresponds to BL `(2x,2u+1/2)`.
Native top-left EL chroma row `j` therefore lies at BL row `4j+1/2`.
Annex-B chroma enlargement alone evaluates BL row `2k-1/2`.
Our native `+1/4` chroma-row adapter adds one BL luma row, giving `2k+1/2`:
the same left-sited grid as prepared BL chroma and our MMR luma guide.
There is no obvious double-shift **under this registration assumption**.
This does not prove SK4 uses the same registration or interpolation.

`test_scaling_probe.py` constructs both layers from the physical affine field
`F(x,y)=128+8x+32y`, not renderer taps. Away from borders, prepared luma layers
match and prepared colour layers match. Omitting/doubling the EL adapter predicts
exact opposite one-luma-row errors. Replicated borders are separate tests.

`scaling_oracle.py` uses exact fractions, Hermite constraints for vertical luma,
point interpolation for vertical chroma, and symmetric horizontal FIR pairs.
It imports no production filter arrays. Tests compare both passes and bounds
statistics against `prepare_frame.py`, covering constants, ramps, impulses,
alternating patterns, asymmetric edges, negative lobes, ties and chunk boundaries.
Separate-pass rounding is observable: one fixture produces code1 whereas
unrounded pass fusion produces code0.

Annex-B negative lobes can exceed declared10bit codes with unsigned16 bounds.
Preparation's existing rejection is an unsupported-input guard, not evidence
that Dolby clamps to1023. We retain this distinction.

## Synthetic backend probes

Generate the13-pattern corpus without video files, NumPy or a GPU:

```sh
python3 tools/yblod/reference/scaling_probe.py generate target/scaler-probes
```

Patterns cover endpoint/neutral constants, distinct Cb/Cr tags, single-code steps,
x/y ramps, impulses, row/column alternation, and edge/overshoot stress.
Inputs are **after the native phase adapter**, not raw top-left decoded frames.
Input size is16x16, output32x32. P010 is tightly packed little-endian Y then
interleaved CbCr, native10bit codes in bits15:6. No range expansion or colour
conversion occurs. Expected planar unsigned16 files preserve stress overshoot.

The tool does **not** invoke hardware. A backend must consume inputs without
hidden format/range/phase changes, synchronize and download, remove stride padding
explicitly, and write each named `CASE-output.p010`. Score all outputs:

```sh
python3 tools/yblod/reference/scaling_probe.py score \
  target/scaler-probes target/backend-outputs target/backend-score.json \
  --backend 'DEVICE; DRIVER; KERNEL; FILTER; CHROMA/RANGE; STRIDES; EXACT COMMAND; DOWNLOAD METHOD'
```

Scoring regenerates canonical inputs/expected values and verifies semantic
contract/runtime code pins, not merely self-declared hashes. It rejects missing
cases, corrupted files, padding and nonzero P010 low bits. Metrics include
even/odd rows and columns. There is no offset fitting or output correction;
native-code differences are not perceived colour errors or certification scores.

Tiny surfaces may be unsupported or select another driver path, and borders
dominate some scores. Rejection does not disprove backend suitability. Next
implement a capability-queried libva probe: first1:1 identity, then supported
larger synthetic surfaces and production-size2x scaling. Extra effective precision
needs an explicit format extension, not silent rounding to P010. Do not measure
playback performance from tiny readback fixtures.

## Intel/AMD offload remains a first-class backend

[VA-API](https://github.com/intel/libva/blob/master/va/va_vpp.h) exposes quality,
interpolation, chroma-position and colour requests, not exact Annex-B coefficient
or per-pass-rounding controls. Query the actual device's capabilities.

[Intel driver selection](https://github.com/intel/media-driver/blob/master/media_driver/linux/common/vp/ddi/media_libva_vp.c)
can prefer different engines by quality choice. Default/advanced interpolation
uses AVS; explicit bilinear uses bilinear. HQ scaling can prefer composition
rather than SFC, consuming graphics resources we want to free. These are source
preferences, not measurements on our device or version-independent guarantees.

In reviewed Mesa26.2.0, [the VA frontend](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.0/src/gallium/frontends/va/postproc.c)
forwards chroma/range information but not interchangeable Intel-style
interpolation controls. [AMD VPE](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.0/src/gallium/drivers/radeonsi/mm/si_vpe.c)
generates its own polyphase filters; [processing](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.0/src/gallium/auxiliary/vl/vl_proc.c)
can fall back to graphics/compute. Successful VA submission alone does not prove
dedicated-engine execution. Format support depends on GPU/driver generation.

Acceptance separates correct geometry/code preservation, documented numerical
differences, and actual offload benefit. Measure video/graphics engine use,
copies/latency and steady-state GPU-surface cost separately from CPU download.
No hardware comparison is completed here; the TV/SK4 are not needed.

## Verified checkpoint

Ollie passes **342 reference tests plus 8 accuracy tests**, no skips, under the
512 MiB hard cap with job swap disabled. This adds 20 tests to the previous
322-reference-test checkpoint. The focused 20-test run takes 1.82 seconds and
peaks at 35,664 KiB process RSS, with zero swaps; these are test costs, not
playback measurements. No playback default, device configuration or capture changed.

Ollie's installed driver is Intel i915 (PCI vendor8086/devicea780), and its
FFmpeg6.1.1 exposes `scale_vaapi` modes/default chroma/range options. However,
the normal `bryan` build account lacks read/write permission to renderD128.
No group membership or device permissions were changed. Driver presence alone
is not a completed hardware comparison; execution needs an authorized GPU-
accessible account or the playback VM's existing GPU context.
