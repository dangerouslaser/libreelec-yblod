# Actual FP32 playback-wrapper checkpoint

The production-shaped wrapper reconstructed both tested frames successfully. Of
24,883,200 unique output codes, 99.9148% matched our integer reference exactly.
Luma was identical; every changed chroma code differed by exactly one 12-bit
step. Cb/Cr aggregate PSNR was 96.26/101.65 dB, using full-range peak 4095.
These are reconstruction-code comparisons, not RGB/display comparisons or a
licensed-decoder conformance result.

Both properly configured FP32 runs recorded 21 accepted FP32 submissions,
zero integer fallbacks, 20 cache hits and one compilation/topology miss. The
second frame uses its existing software-linear enhancement fixture, so this
checks identical composer inputs rather than interchangeable scaling routes.

| Resident reconstruction run | Minimum | Median | Maximum |
|---|---:|---:|---:|
| First frame FP32, initial 1 warmup / 3 samples | 16.64 ms | 17.26 ms | 17.51 ms |
| First frame FP32, 8 warmups / 12 samples | 8.68 ms | 34.63 ms | 47.92 ms |
| First frame integer, 8 warmups / 12 samples | 29.64 ms | 67.48 ms | 81.31 ms |
| Second frame FP32, 8 warmups / 12 samples | 19.78 ms | 31.98 ms | 32.47 ms |

These sequential measurements have substantial jitter. They do **not** confirm
the earlier 46.8% direct-hybrid improvement for the real playback wrapper, and
they are not full playback timing or exclusive GPU kernel timings. The first
run accidentally used environment-variable names not consumed by the probe;
the report explicitly retains its actual default configuration.

The current integer 1917 baseline remained at normal speed without a stall or
failure marker. Its logged approximately 10-to-70-second counter window added
four drops and six skips. The observer ran 76.40 seconds; those counters must
not be presented as a complete 76-second count. Candidate playback results
are now available in the separate completed same-binary ABBA playback report,
FP32_PLAYBACK_COMPARISON.md. This older baseline is not pooled into those controls.

Outstanding: investigate standalone timing jitter and preserve the unresolved
service-shutdown heap-abort caveat. Actual playback composer improvement is
documented separately; it does not retroactively fix these standalone timings.
Successful player stop does not qualify full service shutdown.
