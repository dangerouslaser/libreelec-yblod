# Decoder-to-C checkpoint publication boundary

`native_decoder_checkpoint.py` publishes a narrow, allowlisted summary of a
completed private decoder-to-C reconstruction comparison. It neither executes
the decoder nor creates proof from synthetic configuration. The companion
tests use synthetic records only; passing them is not a real-film checkpoint.

## Required evidence

Before publication, the caller must supply the actual successful producer record
and completed comparison record, separate inventories from the executed producer
and bridge builds, pinned public binaries/libraries/header, and independently
checked private fixture-repair evidence.

The producer must report decoder-owned metadata, an exact raw RPU and exact
active enhancement-layer pixels, requested CRC checking, no warning/error logs,
the expected native instruction ABI, and bounded decoder traversal. The private
instruction digest must match between producer and comparison. The executed
producer and bridge artifacts must match the separately supplied public pins.
Requested CRC checking is not Dolby certification or a universal authentication
guarantee. A local presentation index is not proof of the original movie PTS.

The comparison must complete all twelve native arithmetic stages across all
three prepared components, with every sample byte-exact against the existing
native-C baseline. Its whole-code completion counters must agree, with no raw
sampling queries. Both resource snapshots must retain the bounded memory scope,
zero job swap and zero memory-limit/OOM events. Snapshots are not a final
scope-lifetime peak or a playback throughput measurement.

Producer execution on the LibreELEC VM and reconstruction on Ollie's CPU are
recorded as separate targets with separate resource snapshots. A VM producer
success followed by an Ollie comparison is not a full-frame VM reconstruction
result, even when both use the same matching SDK build.

## Private fixture packaging

The diagnostic source remains a derived test window, not a new movie or a
production decoder input policy. The original fixture is retained. Removing
exactly one independently proven zero byte at EOF is a test-packaging repair;
the retained prefix must be byte-identical. The public summary records only
fixed proof flags and the one-byte removal count, never private fixture hashes,
sizes, paths or contents.

The old extraction parser and the newer SDK parser assign a zero at a four-byte
start-code boundary to different adjacent packets. The correct boundary for the
new parser is derived from exact source bytes and parser source—not chosen to
make observed output pass. This changes packet bookkeeping, not video bytes,
Dolby processing rules or image acceptance. The exact RPU and decoded-plane
checks remain required; no ordinal fallback or relaxed acceptance is introduced.
Rejected attempts must remain documented separately from the successful cohort.

## What becomes public

The summary contains fixed processing-scope text, stage counts and comparison
booleans, completion counters, producer gates, typed FFmpeg runtime versions,
public source/build artifact pins, and bounded resource observations. Separate
producer, bridge and runtime-helper inventories avoid claiming that helper
imports establish a complete executed-build provenance chain.

No raw RPU, decoder-native instructions, decoded pixels, private media/input or
output hashes, paths, arbitrary diagnostic strings or movie-window sizes are
copied into the result. The native arithmetic and decoder bridge remain in the
top-level engine; this publication helper is reference/test tooling only.

`replay_json()` rejects unknown fields, duplicate JSON keys, nonfinite or floating
numbers, type confusion, incomplete counts and invalid source inventories.
Replay validates the published record's structure and stated invariants; it
does not execute a fresh decoder or re-establish omitted private identities.
Actual successful execution must be reviewed before a report is committed.

## Reviewed real-frame checkpoint

[The frame 2296 checkpoint](results/native-decoder-frame-2296-20261005a.json)
records successful decoder production on the LibreELEC VM, followed by full
prepared-frame reconstruction on Ollie's CPU using the same matching SDK bridge.
All twelve stages are byte-exact against the native-C baseline: 8,294,400 luma
samples and 2,073,600 samples for each chroma component, with zero diagnostic
queries. The VM producer traversed 65 frames and 65 packets, with no warning or
error logs. The pre-exit producer memory snapshot was 37,830,656 bytes; the
reconstruction snapshot was 218,251,264 bytes. Both scopes enforced 512 MiB,
with zero observed job swap and memory-limit/OOM events. These are independent
CPU diagnostic stages, not full-frame VM playback or a frame-rate measurement.

This checkpoint does not select enhancement-layer scaling, fractional-value
handling, colour or display-management policy. It does not establish full-player
integration, real-time playback, closer SK4 output or licensed conformance.
