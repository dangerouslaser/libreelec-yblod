# Real-frame reconstruction checkpoint

The independent streaming stages reproduce all twelve saved reconstruction
stage files exactly on prepared frame 2296 of the numbered FEL test. This
checks the implementation against our existing integer reference, not against
licensed Dolby playback. It does not establish correct raw-layer registration,
fractional enhancement processing, display adaptation, or SK4 colour matching.

The comparison covered 8,294,400 luma samples and 2,073,600 samples in each
chroma component. Mapped BL, signed enhancement correction, signed addition,
and reconstructed output all have matching SHA256 hashes. Both implementations
used the same previously prepared 3840×2160 input and matching frame metadata.
All seven prepared input files and all twenty-four output stage files were
rehashed. The saved oracle's reference implementation hash also matches the
current reference source. The extraction, composition, and verification files
match the prepared bundle's recorded source hashes.

The offline Python run completed in 48.78 seconds, with 21,044 KiB process peak
RSS. Its job had a 512 MiB memory limit and zero allowed swap; the reported
cgroup peak, which includes charged file cache, was 175.7 MiB and its swap peak
was zero. These are offline correctness-check resources, not playback timing.

`real-frame-2296-validation.json` contains aggregate evidence and source pins
only. Prepared movie/test pixels, complete frame metadata, RPU payloads and
capture images remain private and are not included in this checkpoint.

## Historical SK4 association

The existing SK4 capture is associated with source frame 2296 by the recorded
visible counter. Its driver timestamp is 95.887 seconds, while the source frame
timestamp is 95.762 seconds. Those timestamps do not prove a matching picture.
Historical comparison reports explicitly retain that limitation.

The historical direct colour output used bilinear left-chroma expansion and
saved fixed transport matrices. Those matrices are a diagnostic transport
coordinate contract, not a TV/EDID target or complete Dolby display-management
model. Reproducing that output or comparing its raw codes with the associated
SK4 capture must be reported separately from reconstruction equivalence.

## Independent colour-stage check

The independently assembled colour path now reproduces the existing **direct
diagnostic** output on this frame exactly: every active-area I/P/T code matches,
and all 24,883,200 packed-frame bytes match. The configuration was associated
with the saved extracted RPU and used the explicitly declared historical
transport matrices. This establishes reproducibility of that diagnostic path,
not improved accuracy or a complete display-management implementation.

It still differs substantially from the associated SK4 output. The full active
rectangle comparison (without fitting, offsets, or spatial adjustment) gives:

| Transport component | Samples | Mean absolute code difference | Maximum |
|---|---:|---:|---:|
| I | 6,178,560 | 72.39073 | 901 |
| P | 3,089,280 | 157.37439 | 2,200 |
| T | 3,089,280 | 40.00688 | 631 |

Both the old and new direct diagnostics produce those same errors. The SK4's
first two metadata packets pass CRC checks, and its transport matrices match.
The visible-counter association and timestamp caveat above still apply. These
are transport-code errors, not perceptual scores or screen measurements.

`real-frame-2296-colour-comparison.json` records exact signed-error histograms,
integer sums, counts, file hashes and parser/source pins. It contains no source
DM, RPU payload or picture samples. The bounded comparison took 15.57 seconds
offline, with 39,092 KiB process peak RSS and zero swap under a 512 MiB limit.

## Reproduction with a private prepared bundle

Run `streaming_composer.py PREPARED_FRAME_JSON NEW_OUTPUT_DIRECTORY` under an
appropriate memory limit. Compare its manifest/input hashes and every stage
record with an independently generated `reference.py` report. Rehash both sets
of files rather than comparing only recorded hashes. Only publish sanitized
aggregate results; the composer reports themselves contain full frame metadata.

## Explicit native integer backend

The C backend also reproduces all twelve reconstruction files byte-for-byte
against both the saved Python stages and the original reference. Native-frame
tests exercise 23 synthetic frame runs and 276 stage-file byte comparisons,
including different depths, MMR guides, disabled residuals and chunk boundaries.
Python mapping, correction and composition calls are deliberately forbidden
while those native tests run, so they cannot silently fall back to the oracle.

On the same prepared real frame, the explicitly selected native backend with
4096-sample chunks took 10.40 seconds for the complete process (10.331 seconds
inside the composer), versus the earlier 48.78-second Python run. Process peak
RSS was 20,004 KiB. The directly read job cgroup peak was 209,944,576 bytes,
including charged cache, with zero swap and no memory-limit/OOM events under
the 512 MiB cap. These single offline runs were not a controlled cache/timing
benchmark and used separately pinned composer source versions. They establish
correct acceleration of this diagnostic, not real-time playback performance.

The native backend is explicit and is not the default. No fractional Y416
policy, new enhancement scaler, display adaptation, Kodi integration or
improved SK4 matching follows from this acceleration result.
