# Native C colour stage: saved frame 2296

The C colour stage produced exactly the same output bytes as the existing
Python colour stage for the saved 3840×2160 frame 2296. Both output files were
read again, independently hashed and compared byte by byte—not merely compared
using their saved report hashes.

| Output | Bytes | Result |
|---|---:|---|
| Unpacked 12-bit transport components | 49,766,400 | Identical |
| Unembedded HDMI transport bytes | 24,883,200 | Identical |

All integer statistics matched exactly. The largest difference between floating
statistics was 5.551115123125783e-17, inside the declared relative tolerance
2e-11 and absolute tolerance 2e-12. This is successful verification of this
native implementation against our Python oracle, not a comparison with the SK4
or proof of licensed Dolby behaviour.

The public, pixel-free evidence is
[native-colour-frame-2296-benchmark-20261005a.json](results/native-colour-frame-2296-benchmark-20261005a.json).
It includes source, configuration, input/output-report, compiler-build and
library hashes, actual output hashes, statistics and memory counters. It does
not contain film pixels, RPU payloads or source-DM coefficients. Original frame
data and output files remain private.

## What was held fixed

The input was the existing completed Python streaming reconstruction. This
isolates colour conversion; it is not a combined native-composer benchmark.
The same verified colour settings and extracted frame metadata were supplied
again. The frame/RPU association was revalidated at execution, without claiming
independent authentication of the original source film.

Chroma expansion, active rectangle, target matrices, PQ-domain policy, final
packing and outside-area replacement were unchanged. C processes each row in
one bounded call, using double precision and the system math library. Python
still handles row preparation, statistics and diagnostic file output. This
does not select a precision policy for fractional hardware-scaled EL samples.

The executed source hashes include:

- `colour_frame.py`: `9422de8c96e6582170c0e0d1be47084f56721f9f4359a19d7da273c6a0c20bdd`
- `native_colour.c`: `2d90cef334b5c0c32a59a7ed8b6a161171f13cc3719821c1395bb534a57753cb`
- `native_colour.h`: `f44655c982da822c8db340155ea2b7694b5c399c4e195ed52e70aa39c088726d`
- `native_colour_stage.py`: `67d6af3a3a3046e3dfcee2dc3a0204b76fb90e31e59c160a30eda83e64799b88`

The wrapper rejects stale build/source/library associations and incompatible
ABI sizes. These checks detect ordinary mismatches and mutations; they are not
authentication of arbitrary untrusted shared libraries.

## Resources and timing

The saved-frame colour call took **67.43 seconds** on Ollie. This includes the
Python row processing and diagnostic output I/O, but excludes compilation and
the subsequent independent file comparisons. It is not playback latency or
isolated C-kernel throughput. No fresh paired Python timing was taken, so this
checkpoint does not claim a measured speedup factor.

The entire run/comparison scope had a 512 MiB ceiling and job swap disabled.
Its peak charged memory was 199,983,104 bytes (190.72 MiB), process peak RSS was
31,220 KiB, and limit-pressure, OOM and OOM-kill counters were all zero. Current
job swap was zero. These are CPU diagnostic resource measurements, not GPU
allocation bounds.

The library was built on Ollie with Ubuntu GCC 13.3.0 and libm, with explicit
`-fno-fast-math -ffp-contract=off` and warning-as-error flags. This is a host
test library, not a LibreELEC-target binary or a deployed Kodi change. Exact
cross-platform floating-point output is not guaranteed by this one result.

## Reproduce

With the existing private prepared frame and verified settings, use fresh
destination names from the repository root:

```sh
systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 tools/yblod/reference/native_colour_stage.py \
  target/native-colour-build-NEW

systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  /usr/bin/time -v python3 tools/yblod/reference/colour_frame.py \
  target/reference-frame-2296-independent-streaming-20261005a \
  target/reference-frame-2296-independent-colour-settings-20261005a.json \
  target/reference-frame-2296-independent-native-colour-NEW \
  --extraction target/reference-frame-2296-v7 \
  --backend native \
  --native-library target/native-colour-build-NEW/libnative_colour.so

cmp target/reference-frame-2296-independent-colour-20261005a/transport_ipt444.u16le \
  target/reference-frame-2296-independent-native-colour-NEW/transport_ipt444.u16le
cmp target/reference-frame-2296-independent-colour-20261005a/unembedded_tunnel.rgb8 \
  target/reference-frame-2296-independent-native-colour-NEW/unembedded_tunnel.rgb8
```

Public synthetic verification needs no private media:

```sh
python3 -m unittest test_native_colour test_native_colour_stage
```

The 14 focused C/wrapper tests passed locally before this run, including actual
frame-runner output comparison with Python colour arithmetic forbidden during
native execution. No device capture, playback default, output mode or hardware
scaler setting changed in this checkpoint.
