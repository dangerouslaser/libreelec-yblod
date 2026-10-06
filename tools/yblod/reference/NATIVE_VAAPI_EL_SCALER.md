# Borrowed VAAPI enhancement-layer scaler

Experimental real VAAPI helper, not a default Kodi caller. It borrows an
initialized `VADisplay` and a caller-established P010 input surface. It owns one
full-size P010 output surface, a VideoProc configuration/context and pipeline
buffer. No CPU pixel upload/download/mapping and no EGL import are performed.
The borrowed display is never terminated.

The explicit configuration admits even half-resolution EL input and exactly
2x output, bounded to3840x2160. Input top-left chroma becomes declared left
chroma; input/output BT2020 standards and full/reduced code-range conventions
match. The caller chooses FAST scaling or BILINEAR interpolation separately
from the optional FAST pipeline hint. P010 surface advertisement, reported
pipeline formats/colour standards, size limits and pipeline hint are checked.
Raw `filter_flags` are available through the getter: these encoded selectors
are not treated as a bitset promising a particular interpolation implementation.
Submission acceptance is not proof the driver honored the precise requested
kernel, used a particular Intel unit, or produced Annex-B-equivalent pixels.
Actual driver output must still pass the whole-P010 compositor gate; no low
bits are rounded away. AMD qualification would need its own measurements.

`submit` waits for the producer with finite `vaSyncSurface2`, then submits VPP;
`finish` waits for output with a separate finite timeout, each at most5seconds.
Successful finish alone publishes the owned surface ID. Keep input alive until
completion; output consumers must finish before another submission or destroy.
The helper has no external-consumer fence and cannot establish this itself.
A normal output timeout retains pending resources and allows retry, not reuse.

RenderPicture or EndPicture failure quarantines the handle. A non-timeout
output synchronization failure also quarantines it. Subsequent submit, finish
and destroy make no VA calls and expose no output. Do not free/recycle input,
output or associated storage. An old output-surface wait cannot establish
failed-context quiescence. Only after the display owner has completed whole
display/device teardown and invalidated its objects may it explicitly call
`abandon_after_display_teardown(...,1)`, which frees host state only. This caller
assertion is not machine-verifiable proof. A failed ordinary destroy retains
remaining names for retry and prevents further submissions.

The primary [libva core API](https://intel.github.io/libva/group__api__core.html)
documents nonblocking EndPicture and surface-associated synchronization;
it does not guarantee quiescence after a failed submission. The conservative
quarantine policy is ours, not a claimed driver recovery guarantee. Pipeline
[capability documentation](https://intel.github.io/libva/structVAProcPipelineCaps.html)
labels filter flags as extra flags, not an independently enumerated kernel list.

The saved synthetic Intel hardware gate used32x32 input and64x64 output twice,
through this real borrowed helper: one constant frame and one ramp. All12,288
read-back output words had six zero low bits; the constant frame had zero word
mismatches. The ramp has observations, not an independently specified scaling
oracle. Advertised raw filter flags were0; successful BILINEAR/FAST-hint
submission does not establish exact kernel selection. Peak job memory was
53,182,464bytes, with no swap or memory events; Kodi remained active with the
same process/start identity. Selected source, executable, collector and nine
runtime files were unchanged. This is neither whole-playback performance nor
all-driver/all-resolution qualification, EGL import evidence, or loaded-driver
source attestation. See `VAAPI_EL_SCALER_RESULTS.json`.

The real-SDK configuration probe contains21 checks. The replacement-API lifecycle
probe exercises success, pending timeout/retry, failed destruction/retry,
RenderPicture failure, EndPicture failure and non-timeout output-wait failure.
Its function bodies replace libva operations with deterministic results while
using the actual SDK declarations. This is control-flow evidence, not a driver
or hardware test. Replay uses `YB_VAAPI_EL_SCALER_CONTRACT_PROBE` and
`YB_VAAPI_EL_SCALER_FAULT_PROBE`; missing binaries produce explicit test skips.
