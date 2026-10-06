# Base layer QSV duration and instruction association diagnostic

This experiment checks whether native HEVC and the experimental QSV decoder return the same pictures with the same Dolby instructions and original packet durations. It keeps the existing three-frame literal P010 comparison and adds checks for every returned frame in a finite packet window. It does not qualify Kodi playback, HDMI output, full-film decoding or performance.

## Current qualification

The CPU checks pass: 14 duration-conversion cases, the bounded snapshot and lifecycle fixtures, 17 individual picture-property diagnostic faults, and 14 parameter-set insertion cases. Their recorded peaks are 99,213,312 bytes for the combined compile and CPU checks, and 26,734,592 bytes for the insertion contract. Both containers had a 512 MiB memory limit, no swap, one CPU, no network and no GPU access. All memory event counters were zero.

The earlier hardware attempt reached 23 submitted packets and 20 returned frames on each decoder, with 19 matching instruction pairs before the next pair was rejected. The precise rejected field is unresolved. That attempt used the insertion-corrected predecessor of this diagnostic source, not the latest field-diagnostic binary. The latest binary has only compile and CPU qualification. No tolerance or comparison gate has been relaxed.

The earlier selected-three-frame raw comparison remains a separate result in [the compatible parameter candidate](../native_qsv_bl_compatible_param_candidate/README.md). It does not establish equality for every frame in this broader window.

## Source behavior

`native_qsv_bl_duration.h` converts positive packet durations into integer microseconds with checked arithmetic and explicit rounding. Zero remains unknown; negative values, overflow and an unrepresentable positive result fail. Both decoder packet clones and the independent instruction-event record receive the same duration. Returned frames must match their own event duration, even if both decoders happen to agree on an incorrect duration.

The independent scanner uses FFmpeg's `hevc_mp4toannexb` filter and verifies every original NAL unit and its order literally. The original diagnostic incorrectly required inserted parameter sets to be at packet byte zero. FFmpeg 9 instead inserts its complete hvcC-derived prefix immediately before the first IRAP, or the first parameter set when parameter sets precede that IRAP. Preceding AUD or SEI units remain before the insertion. The corrected guard implements that exact two-pass rule and rejects unrelated injection, relocation, dropped or rewritten data.

Lifecycle mode defaults off. The off route now sends NULL input to finish the selected finite window and requires both decoders to reach decoder EOF, with all admitted events returned and paired and no pending snapshots. This is controlled-window EOF, not natural end of the film. Missing outputs, including any leading-picture issue, fail the qualification rather than being silently excluded.

The failure-only `pair_rejection` object contains a numeric reason and decoder route, expected and observed durations, and equality booleans. `comparison_evaluated` distinguishes an actual comparison from a rejection before comparison. It contains no source timestamps, media bytes, content hashes or paths. Reasons are: 1 invalid input; 2 absent event; 3 duration mismatch; 4 duplicate association; 5 invalid snapshot; 6 snapshot budget; 7 allocation; 8 property copy; 9 retained ownership; 10 property, resolved-metadata or raw-RPU mismatch.

## Reproduce the CPU checks

The bounded launchers target the existing LibreELEC reference layout on Ollie. They require the pinned SDK image `sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e`, the read-only LibreELEC SDK, and the independently attested compatible-parameter FFmpeg copy prepared by the earlier candidate helpers. That copy supplies the original native HEVC decoder and the experimental `hevc_qsv` decoder. The launchers never replace SDK libraries or sources.

Run from this directory on the reference host:

```sh
python3 run_payload_insertion_contract.py
python3 run_duration_window_probe_compile.py
```

Each launcher creates a fresh, owned container and output directory and refuses to overwrite an earlier attempt. It verifies exact container limits, mounts and image, enforces a deadline, and retains terminal logs. The combined compiler verifies ten source hashes, all eight candidate libraries, configuration and native decoder ABI guards before and after its CPU-only checks. These are reference-layout reproduction helpers, not a portable installer.

For another SDK layout, compile the standalone sources and fixtures against that independently validated FFmpeg build and report its own source and runtime identities. Changing the reference guards does not inherit the recorded qualification.

## Hardware testing restrictions

The dual-decoder hardware diagnostic uses a separately authorized 1536 MiB test allowance with no swap and one CPU. This is a probe budget, not a Kodi memory or performance result. Hardware testing requires the complete actual-code and Intel-device identity checks, at least 6 GiB host memory available before launch, and an abort below 3 GiB. Do not run it alongside the playback benchmark or a large build. The current broader picture and instruction comparison is still unresolved; lifecycle hardware testing follows only after the ordinary window passes.
