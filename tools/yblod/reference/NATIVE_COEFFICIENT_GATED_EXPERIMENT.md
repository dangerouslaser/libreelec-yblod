# Coefficient-gated MMR shader experiment

This is an unadopted alternative shader, not a change to the canonical composer. It avoids work whose selected metadata coefficients are zero while retaining surviving accumulation order, nested integer floors, existing overflow admission, sampling, polynomial mapping, NLQ and output limits. Gates can differ across pixels selecting different segments; they are not guaranteed SIMD-uniform.

The unchanged production image probe compiled and exercised each shader in A/B/B/A order on the same prepared 3840×2160 inputs. Each invocation compared all 12,441,600 reconstructed codes against the existing C engine after a complete 49,766,400-value CPU stage gate. This checks reconstruction codes, not complete colour rendering, TV output or playback. No attempts failed or were retried.

The saved report contains every measured sample. Baseline A1 was about 67 ms, A2 about 33 ms; candidate runs were mostly 67–81 ms, with one 55 ms sample. There is no established speed gain, and the shader is not adopted. These host submission/completion measurements are not exclusive GPU kernel timings or playback FPS.

Each run used a fresh 512 MiB/no-swap scope, CPU quota 100000/100000 and a 60-second external systemd deadline. All saved memory events were zero; observed CPU throttling deltas were zero. Peak values are in-scope snapshots, not an assertion of the eventual final peak. Wrapper-window CPU usage includes the CPU oracle and bookkeeping. GPU frequency snapshots are only before/after observations, not continuous frequency, busy or power measurements. Live Kodi and selected runtime/input/artifact pins remained unchanged.

Reproduce using the unchanged `native_gpu_composer_image_probe` executable with either `native_gpu_composer_backend.comp` or `native_gpu_composer_backend_coefficient_gated.comp`, identical prepared inputs and the documented image-probe CLI. Alternate A/B/B/A, retain full-frame exact gates, limits and cleanup checks, and record competing workload/frequency context. The alternative source can be diffed against the canonical shader; do not replace the canonical shader for this experiment.

The three host tests check signed coefficient masks, orders 1–3, every accumulation prefix and unchanged non-MMR source sections; they do not compile GLSL. Compiled signed/higher-order/multipivot custom-context coverage remains unrun. Further qualification is required before any adoption. Timed passes check the frame error flag only; exhaustive image comparison occurs in the untimed gate.
