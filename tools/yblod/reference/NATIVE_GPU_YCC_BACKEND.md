# Explicit reconstructed chroma expansion

`engine/experimental/native_gpu_ycc_backend.h` is an isolated C wrapper around the explicit reconstructed420-to-RGBA32F shader. It consumes completed depth12 R16UI planes and sampling contract1 only. Other depths/policies return unsupported rather than quietly choosing a conversion.

The declared diagnostic policy uses chroma coordinates x/2,(y−0.5)/2, clamped edge extension and bilinear interpolation. Output is unrotated Y,Cb,Cr code/4096 with alpha1. No chroma rounding, colour conversion, TV targeting or Dolby normative claim is made here.

The caller owns a dedicated current desktopGL context and borrowed inputs. The wrapper owns one full-size RGBA32F image and a four-byte error flag. Submission performs one full-frame8x8 compute dispatch and inserts one fence. Finish has a finite at-most-five-second wait and rejects the whole frame on invalid codes. Output descriptors are unchanged on failure. Consumers must synchronize before the next submission overwrites this single output set.

Integer inputs must have R16UI format, expected plane dimensions, default swizzle and nearest MIN/MAG filters; external samplers are unbound. This completeness check matters even when the shader uses texelFetch. No EGL context/display is created inside the production wrapper; the caller must restore its own EGL bindings before Kodi GLES rendering.

The separate synthetic runner exercises the actual API on4x4 and8x6 fixtures, including resize, edges,0/4095 codes, frame identity, busy input/output ownership, invalid4096-code frame rejection and invalid integer-filter rejection. Its independent CPU oracle uses integer bilinear-weight numerators divided by32768; all fixture weights/codes are exactly representable in float32. It compares all256 output float bit patterns. This is a narrowly scoped exact expansion gate, not a colour accuracy, performance or live decoder test.

Host-only tests validate the pure plan guards and source ownership structure. Actual GPU execution requires the separate reviewed, pinned synthetic checkpoint. Future orchestration must retain frame/PTS/preparation contracts and connect this output to explicit colour conversion and the tested desktopGL-to-GLES image bridge.

[Actual synthetic checkpoint](results/native-gpu-ycc-image-synthetic-20261005q.json) passed all256 float-bit comparisons, two invalid-code frame rejections and four invalid integer-filter rejections. Peak memory49,651,712 bytes; swap and all memory events were zero. Kodi and pinned runtime remained unchanged. Aggregate comparisons are recorded; this checkpoint does not serialize the output arrays for external recomputation.
