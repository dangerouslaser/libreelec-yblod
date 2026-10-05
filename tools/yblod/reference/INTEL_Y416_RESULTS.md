# Intel production-format constant probe: capability gate and diagnostic

2026-10-05, isolated LibreELEC VM192.168.1.175, Intel8086:9a49/i915,
iHD26.3.5 (3de4708), libva2.24.0/API1.24. No Kodi, playback or display settings
changed. These are synthetic private-surface tests, not playback benchmarks.

The requested72-job matrix stopped fail-closed at invocation25:

- All12 copy and12 submitted P010 same-size FULL constant gates were byte-exact.
- The first Y416 conversion was not submitted. The driver surface capability
  list advertised Y412 (`0x32313459`), but not Y416 (`0x36313459`).
- The probe rejected this before output allocation/VPP submission. Thus this
  run provides **no Y416 pixel, precision, range or spatial-phase measurements**.
- No format substitution or fallback was attempted. The remaining47 planned
  conversion invocations did not run.

The source production bridge explicitly requests Y416/YUV444_12, not Y412.
This discrepancy needs separate driver/allocation investigation before treating
the earlier P010→P010 tests as production-equivalent. An unadvertised format
does not alone prove allocation/submission is impossible; this probe deliberately
requires the advertised contract. The installed Kodi binary has not been tied
to the inspected source commit.

Reproduction:

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_check.py ./vaapi_scaler_probe-v10 y416-constant-run-v10 \
  --width 64 --height 64 --repeats 2
```

The aggregate report `results/intel-y416-constants-v10.json` includes input,
source/helper and executable hashes, exact arguments, failure and API-log hashes.
Raw synthetic data/logs remain in the VM's private test directory. No film layers
or device captures are included in the report or public source.

The probe builds with GCC16.2.0 using `-Wall -Wextra -Werror` against the existing
LibreELEC SDK in a512MiB container. The423 reference tests (including14 compiled
pre-GPU guards) and8 accuracy tests pass in bounded scopes. This is test-tool
validation, not hardware conversion acceptance.

## Separate exact-format allocation/submission diagnostic (V11)

After the strict V10 failure, source inspection established that Intel's general
surface allocator recognizes explicit Y416 independently of the VideoProc list.
An explicit `--allocation-diagnostic` run retained the exact requested format,
recorded `output_surface_advertised:false`, and did not change the strict default
or use a fallback. Its72 invocations completed:24 exact P010 transport gates and
48 same-size Y416 observations, with both FULL and REDUCED conventions and two
repeats. Each conversion allocated, submitted, synchronized and downloaded the
exact format successfully on this configuration.

For all12 constants/channel tags in both range conventions:

- All repeats were byte-identical; FULL and REDUCED outputs were byte-identical.
- Observed little-endian word order was U/Y/V/A, resolved by distinct channel tags.
- Each colour word equalled its input10-bit code multiplied by64 everywhere.
  Alpha was uniformly65535 and is not a colour sample.
- Dark/bright endpoints and values outside nominal limited-range bounds were
  preserved in this corpus; no endpoint clamp or brightness shift was observed.
- Colour low6 bits were zero for these **constant** inputs. This does not measure
  scaling's fractional precision or establish effective10/12/16-bit precision.

The tagged input Y512/Cb384/Cr640 produced raw words24576/32768/40960/65535.
No raw bits were discarded. Same-size420→444 conversion with spatially constant
chroma cannot establish chroma alignment or a scaling filter, and these results
are not evidence that frames match the SK4 or that the backend is qualified.

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 hardware_y416_check.py ./vaapi_scaler_probe-v11 \
  y416-allocation-diagnostic-v11 --width 64 --height 64 --repeats 2 \
  --allocation-diagnostic
```

Aggregate evidence: `results/intel-y416-diagnostic-v11.json`. Python peakRSS was
24704KiB; elapsed1.04s is test time, **not playback performance**. Full427
reference tests, including16 pre-GPU compiled guards, and8 accuracy tests pass
under bounded scopes. Next: spatial Y416 tests with independently defined444
coordinates, preserving fractional raw words, before full-size acceptance.
