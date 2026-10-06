# Original CroqueMr versus experimental reconstruction

This compares source behaviour, not a measured original-build benchmark.
The original is pinned to CroqueMr/intel-dv-libreelec commit
`0008daa71e8233891fcf712d7e0f59fe65eaab3d`. Our imported Kodi code also
included fork changes, so disabling the native engine does not recreate that
pristine original.

| Area | Original CroqueMr | Current experimental engine |
|---|---|---|
| Base-layer calculations | libplacebo FP32 GPU math | Actual libplacebo-generated FP32 math in a standalone C engine |
| Enhancement-layer enlargement | libplacebo shader plane sampling | Intel VA-API video processing through the native adapter |
| Processing order | Sample planes onto the reference grid, then reconstruct | Compose prepared native 4:2:0 samples, then expand chroma |
| Correction boundaries and rounding | Floating-point NLQ, including neutral-value suppression | Integer NLQ and explicit discrete rounding |
| Precision | Already requested 32-bit intermediates | FP32 base-layer math plus integer discrete operations |
| Code organisation | Kodi and libplacebo patches | Standalone C engine with a Kodi adapter |
| Resource handling | Existing renderer ownership | Native generation/consumer leases, fences, bounded shader cache and fallback |
| Performance against original | Not measured in this experiment | Needs the pinned original on the same hardware and scenes |
| Accuracy against original | Not measured in this experiment | Needs matched input frames and output policies |

Different processing order is not itself proof of better accuracy. The current
engine intentionally uses consistent binary-domain sample/pivot normalization;
it is not simply the original shader moved into a new file. Output-bound and
transport policies also need to be compared explicitly.

## Measurements available now

These compare our native integer control with our selectable FP32 hybrid,
**not** with the original CroqueMr build or with an SK4 hardware reference.

| Measurement | Native integer control | FP32 hybrid |
|---|---:|---:|
| Weighted reconstruction wait during four short 1917 playback runs | 16.623 ms | 9.245 ms |
| Reduction in that wait | Reference | 44.39% |
| Exact reconstructed samples across two unique 4K test frames | Reference | 99.9148% |
| Largest reconstructed sample difference | Reference | 1 code at 12-bit |

The timing is reconstruction waiting, not whole-player throughput. The pixel
comparison covers 24,883,200 samples; luma was exact and the changed samples
were chroma. Short playback tests did not qualify clean shutdown. See
[playback results](FP32_PLAYBACK_COMPARISON.md) and
[wrapper validation](FP32_WRAPPER_VALIDATION_SUMMARY.md) for scope and details.

## Source anchors

- [Original renderer parameters](https://github.com/CroqueMr/intel-dv-libreelec/blob/0008daa71e8233891fcf712d7e0f59fe65eaab3d/patches/kodi/kodi-9990-native-dv.patch#L4451): already requests FP32 intermediates; original transport includes RGB clamping.
- [Pinned libplacebo plane sampling](https://github.com/haasn/libplacebo/blob/e2972fdd09adacd383656738d7d280f0cd84a761/src/renderer.c#L1943): sampling/combining planes precedes colour decoding and reconstruction.
- [Pinned reshape and composition](https://github.com/haasn/libplacebo/blob/e2972fdd09adacd383656738d7d280f0cd84a761/src/shaders/colorspace.c#L337): base-layer reshape and enhancement correction.
- Current implementation: `engine/experimental/native_libplacebo_reshape.c`,
  `engine/experimental/native_gpu_composer_fp32.c`, and
  `engine/src/native_composer.c`.

The earlier yblod QuickSync/chroma changes are our changes, not pristine
CroqueMr behaviour. Historical README performance figures are not comparable
to this matched native integer-versus-FP32 experiment.
