# BL QSV picture-association v2 experiment

A controlled Saving Private Ryan window passed: 725 access units returned and paired once on both decoders, with matching source PTS, known best-effort timestamps, positive durations, independent native Dolby instructions and RPU bytes. Three selected 4K pictures matched literally in all nine P010 planes. Genuine Intel GPU use and the mapped code closure were verified.

This is not Kodi playback, Dolby conformance, whole-film EOF, or performance qualification. No previous-RPU-reference cases occurred in this window.

## Why the comparison contract changed

The earlier diagnostic correctly identified a KEY mismatch; the product now preserves native HEVC IRAP classification through the exact picture token. The next diagnostic rejected only packet DTS. FFmpeg defines that field as the timestamp of the packet triggering frame return, which can differ between decoder buffering implementations. No product DTS was rewritten.

The new explicit contract keeps presentation identity, duration, Dolby instructions, geometry, flags, color plumbing and literal sample checks mandatory. Transport DTS is recorded separately for every pair: 60 of 725 differed, with a maximum 83,000 microsecond route delta; three pairs had unknown DTS on both routes. All properties, including transport DTS, matched on the three selected pictures. Read [COMPARISON_CONTRACT.md](COMPARISON_CONTRACT.md) for the precise boundary.

## Reproduce

The CPU fixture uses the pinned LibreELEC SDK image and the copied compatible-parameter FFmpeg build, both referenced by the supplied controllers. From a fresh source directory, run:

```sh
python3 run_duration_window_probe_compile.py
```

It runs with 512 MiB, no swap, one CPU, no GPU/network. Fourteen duration cases, actual pair/property/unknown-timestamp faults, bounded drain mocks and twelve observer mocks passed. The first attempt omitted new transport counters in one synthetic drain setup; only that fixture was corrected.

The hardware controller requires the isolated key-flag library build at the exact pinned target layout, the freshly compiled probe, a private input path supplied through `PRIVATE_INPUT_PATH`, the established identity helpers in the repository reference directory, and idle Kodi. It uses a 1536 MiB **test-only** allowance, no swap, one CPU, a 170-second child deadline and 6 GiB/3 GiB host-memory safeguards. Do not interpret its eight-second offline run as playback speed.

The supplied hardware controllers retain exact output names to reproduce this recorded attempt. They fail rather than overwrite an existing attempt. Previous failed diagnostics are preserved in their reports; they are not retroactively described as passing.

## Next qualification

Lifecycle ON currently fails closed. Controlled drain, flush/reopen and held mapped-frame ownership need the v2 epoch contract and separate tests. Actual typed Kodi mapped-buffer admission, packet-duration forwarding and player presentation must still be checked. Default production decoding remains unchanged.
