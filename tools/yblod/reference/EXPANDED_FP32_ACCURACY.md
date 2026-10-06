# Expanded FP32 arithmetic check

Two additional unique frames (1943 and 1960) from the numbered FEL test clip
passed complete CPU-reference comparisons on the Intel Tiger Lake VM. Both
integer GPU controls were exactly equal to the native integer CPU reference.

| Frame | Luma samples changed | Cb samples changed | Cr samples changed | Largest absolute difference |
|---|---:|---:|---:|---:|
| 1943 | 0 / 8,294,400 | 2,166 / 2,073,600 | 3,153 / 2,073,600 | 1 code |
| 1960 | 0 / 8,294,400 | 2,514 / 2,073,600 | 1,855 / 2,073,600 | 1 code |

Each code is a 12-bit reconstructed output sample. Neither test had a
difference larger than one code. Both selected the actual FP32 playback
wrapper: 21 accepted FP32 operations, zero integer fallback, one shader cache
miss and 20 hits, zero generation/compilation failures, and successful cleanup.

Together with the [first two frames](FP32_WRAPPER_VALIDATION_SUMMARY.md), this
covers 49,766,400 reconstructed samples across four unique frames: 30,892
changed (all chroma), or approximately 99.9379% exact samples. This is not a
claim that 99.9379% of displayed pixels match licensed Dolby hardware.

## Performance checkpoint

| Frame | Integer median | FP32 median |
|---|---:|---:|
| 1943 | 16.751 ms | 9.104 ms |
| 1960 | 16.677 ms | 8.919 ms |

These are sequential standalone measurements, 8 warmups and 12 samples per
route, of resident-input submit/completion time. They exclude per-frame
preparation, hardware import, full-image readback, and normal player work.
They are not exclusive GPU kernel timings or an original-Croque benchmark.
The matched actual [1917 playback comparison](FP32_PLAYBACK_COMPARISON.md)
is the stronger evidence for a playback improvement.

## Scope

The fixtures use verified decoder-owned instructions and source association,
but historical software/linear enhancement preparation. Live playback uses
different preparation/scaling. These results qualify same-input reconstruction
arithmetic, not end-to-end display accuracy or the live scaler. Full-frame
private inputs and outputs are intentionally not committed.

The FP32 frame1943 diagnostic peaked at 249,417,728 bytes under a 512 MiB,
no-extra-swap, one-CPU cap, with zero memory-limit/OOM events and zero swap.
Reference: native integer CPU composer, not SK4 or Dolby conformance output.
