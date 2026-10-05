# Intel production-format constant probe: initial capability gate

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
