# Full-HD prepared-frame validation and colour bridge

2026-10-05, Ollie. No TV, VM, movie pixels or real RPU used. Existing playback
and colour policies remain unchanged.

Verification on Ollie: 567 reference tests and 8 accuracy tests passed (575
total, no skips), under the 512 MiB/no-job-swap ceiling.

## Larger prepared input

`make_streaming_demo.py` now generates deterministic prepared native layers in
bounded chunks. The 1920x1080 fixture includes a piecewise polynomial, all three
MMR orders with an explicit synthetic guide, distinct channel correction
parameters, a binding maximum, and a zero maximum. Scalar parameters are
arithmetic fixtures, not a claim of a complete conforming Dolby bitstream.

Both the new runner and unchanged reference processed this bundle successfully.
`cmp` verified exact equality of all twelve mapped, correction, sum and
reconstructed stage files. Each job ran in its own 512 MiB/no-job-swap scope.

| Runner | Maximum process RSS | Wall time |
|---|---:|---:|
| Streaming, chunk4096 | 20172 KiB (19.70 MiB) | 10.42 s |
| Original whole-plane reference | 72876 KiB (71.17 MiB) | 8.16 s |

These are `/usr/bin/time -v` process measurements from one sequential run,
streaming first. They do not include cgroup page-cache usage or establish a
controlled performance benchmark. Both reported zero swaps and exit status0.
The streaming implementation uses substantially less process memory here but
is slower; neither time is a playback rate or GPU performance result.

Public evidence:

- `results/streaming-full-hd-composer-v1.json`: exact runner/helper/input hashes
  and stage counts, extrema and hashes.
- `results/streaming-full-hd-input-v1.json`: generator source hash, manifest hash
  and hashes for the entirely synthetic input planes.

Raw generated planes and outputs stay in Ollie's temporary scratch directory,
not the public repository or LibreELEC VM.

## Reproduce

From the repository root, using a new destination directory:

```sh
mkdir -p target
python3 tools/yblod/reference/make_streaming_demo.py target/full-hd-input \
  --width 1920 --height 1080
python3 tools/yblod/reference/streaming_composer.py \
  target/full-hd-input/frame.json target/full-hd-streamed
python3 tools/yblod/reference/reference.py \
  target/full-hd-input/frame.json target/full-hd-original
```

Compare corresponding stage files or their report hashes. Allow roughly
100 MiB of scratch space for this input plus both sets of diagnostic outputs.
On Ollie, use the documented `systemd-run` memory/swap limits around each job.

## Colour-path connection

`test_streaming_colour_bridge.py` verifies that the new runner's reports and
planes work with the existing inspection and diagnostic colour helpers. For a
separate 32x18 synthetic frame and explicitly synthetic identity colour
instructions, both runners produce exactly equal intermediate colour arrays,
final transport codes and unembedded packed bytes. Strip heights1/7/64 produce
equal final codes with no seam changes.

Eight additional synthetic colour triples agree with the existing independent
60-digit Decimal oracle. That covers the declared project transport convention;
it does not establish a licensed Dolby transport or out-of-range colour policy.

This bridge reuses `output_frame.convert`, `expand_left` and `pack`. It is not an
independent replacement colour engine, does not exercise real-RPU provenance,
and does not produce playable HDMI with embedded dynamic metadata. Illustrative
bilinear chroma expansion and extended-PQ behavior remain labelled diagnostics.

Next extract the colour stage into an explicitly configured reusable component,
keeping chroma sampling, PQ-domain handling and output transport as separate
decisions rather than silently inheriting the diagnostic defaults.
