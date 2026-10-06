# Metadata-only colour entry: synthetic qualification

The original reconstructed-colour entry and the metadata-only entry produced
bit-identical complete RGBA32F outputs with three synthetic input sizes. Each
run compared 33,177,600 float components across the full 3840x2160 output, using
one renderer sequentially and row-streamed checks rather than duplicate CPU
float images. Active-area margins matched; invalid pairing and invalid metadata
were rejected without stale output readiness. This qualifies the inherited RGB
stage, not HDMI transport, a film frame, SK4 matching or Dolby conformance.

| Synthetic source | Float components compared | Peak cgroup memory | Probe exit |
|---|---:|---:|---:|
|64x64|33,177,600|300,564,480 B|0|
|1920x1080|33,177,600|359,559,168 B|0|
|3840x2160|33,177,600|484,073,472 B|0|
|3840x2160, corrected complete-packet probe|33,177,600|507,576,320 B|0|

All four runs reported successful cleanup, two rejected invalid-entry cases,
zero memory-limit/OOM events and zero swap under the 512 MiB diagnostic cap.
Before/after artifact hashes, Kodi service PID/start identity and idle-player
checks matched. The 4K guarded repeat also retained a successful controller
trace. No timing or playback speedup is claimed by these output tests.

## Qualification caveats retained

- The initial synthetic metadata factory omitted a required L1 extension and
  failed mapping/preparation. The corrected factory passed a CPU-only gate
  before these GPU checks.
- An earlier 4K attempt completed its pixel probe but its external guard exited 1
  for an unexplained reason. It is not counted as a qualified run; the fresh
  traced 4K repeat above passed the whole guard.
- Independent review found that the first probe compared packet count and only
  the leading packet word(s), not complete packet contents. Full RGB output and
  margin comparisons are unaffected. The probe is corrected to compare all 128
  words per packet and reports explicit coverage. A new guarded 4K run then
  matched all 128 packet words, all 33,177,600 output float components and the
  active-area margins, with successful cleanup and external guard exit 0.

The corrected complete-packet probe SHA256 is
`d52770e06a5826c5e9784e75255c40e1d31dd3e0abf05fe3056d7fdc2a72bbb7`.
The qualified earlier pixel-only probe SHA256 is
`2f1569a0071809160f8644bb6fa49cf401a928b339ced5fdffe512259d43eb35`.
Private synthetic checkpoint files were removed after retaining scalar evidence;
they are reproducible with the published source. No input pixels, debug shader
dumps or private paths/hashes are included here.
