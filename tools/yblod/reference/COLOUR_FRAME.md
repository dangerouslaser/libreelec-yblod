# Bounded diagnostic colour-frame runner

`colour_frame.py` connects completed prepared-frame reconstruction to the new
scalar colour component, explicit chroma expansion and independently implemented
diagnostic byte packing. It reads one output row at a time, caches at most two
rows per input plane, and never creates full-frame float arrays. JSON metadata
has a separate8 MiB byte allowance.

## Reproducible synthetic workflow

Use fresh destinations from the repository root:

```sh
mkdir -p target
python3 tools/yblod/reference/make_streaming_demo.py target/colour-input
python3 tools/yblod/reference/streaming_composer.py \
  target/colour-input/frame.json target/colour-composed
python3 tools/yblod/reference/make_colour_demo.py \
  target/colour-composed target/colour-settings.json \
  --target project-transport-diagnostic \
  --pq-policy extend-positive-negative-to-zero
python3 tools/yblod/reference/colour_frame.py \
  target/colour-composed target/colour-settings.json target/colour-output
```

The demo helper supplies **synthetic identity source instructions**, not a real
RPU. It only accepts a result labelled synthetic and never overwrites settings.
That label is an accidental-use guard, not cryptographic proof of origin.
Target and PQ policy are required CLI choices. There is no automatic selection
of a display target or an asserted correct out-of-range rule.

## Configuration and checks

The JSON configuration is hash-bound to the exact composer report and supplies:
source colour instructions, target matrices/offsets,4096 code scale, PQ policy,
`bilinear-left-diagnostic` expansion, an explicit active rectangle, and explicit
outside-area target codes. No defaults fill in missing choices.

The runner reuses global manifest validation and requires complete12-bit PQ
420-left reconstructed output. It checks consumed stage paths, regular-file
types, dimensions, lengths, native code ranges and hashes before creating the
output. File metadata checks at the end catch ordinary mid-run source changes;
they are not an immutable/adversarial snapshot guarantee.

**Remaining provenance limitation:** the configuration is tied to the
reconstruction, but the supplied source colour instructions are still
caller-declared. They are not independently verified against that video's
extracted RPU. The result labels this limitation explicitly. This runner must
not be presented as a fully provenance-checked real-video colour pipeline yet.

## Output and policy boundaries

- `transport_ipt444.u16le`: interleaved three-component target codes.
- `unembedded_tunnel.rgb8`: diagnostic packing with second/third target
  components sampled at even horizontal positions.
- `output.json`: source/configuration pins, stage hashes and intermediate range
  counts, published only after successful processing and stream closure.

The target-coordinate filename does not prove licensed Dolby coordinate
conformance. These bytes have **no embedded dynamic metadata or HDMI signaling**
and are not playable Dolby Vision HDMI output. No TV brightness adaptation or
display gamut mapping is implemented.

Bilinear expansion is explicitly an illustrative project choice, not the
resolved licensed chroma filter. PQ handling follows the caller's policy from
`COLOUR_STAGE.md`. Active-area replacement happens after conversion; statistics
include all converted pixels before that replacement. A strict policy can
therefore reject an excursion even outside the selected active area.

New output directories are required. Input, domain or I/O failures may leave
partial diagnostic files but no completed output report. Report publication
does not overwrite existing files; failure to remove a temporary hard link
after publication cannot turn successful conversion into a reported failure.

## Verification

Tests cover exact output codes/bytes against the existing diagnostic helpers on
a synthetic frame, bounded row caches, explicit choices and report binding,
corruption/path/regular-file/depth guards, input changes, active-area replacement,
packing recovery, no-overwrite behavior and completion publication failure.

On Ollie, 585 reference tests plus8 accuracy tests passed (593 total, no skips)
under a512 MiB ceiling with job swap disabled. The synthetic512x256 CLI run
completed successfully: `/usr/bin/time -v` reported19432 KiB process RSS,
3.25 s elapsed and zero swaps. This single scalar diagnostic run is not a
playback benchmark and process RSS does not include cgroup page-cache usage.

Public source-pinned evidence is in `results/colour-frame-synthetic-v1.json`
and its exact composer report, `results/colour-frame-synthetic-composer-v1.json`.
Only reports are published; no film pixels, RPU payloads or raw output planes
are included. The configuration in the result is entirely synthetic.

Next verify source-DM association against extracted RPU evidence, validate real
prepared frames, and separately resolve chroma and out-of-range behavior before
accelerated playback integration. This component selects none of those policies
as the correct licensed-player behavior.
