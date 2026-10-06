# Experimental desktop GL to GLES output bridge

`native_egl_output_bridge.c/.h` implements an EGLImage sibling boundary between
a desktop GL producer texture and a GLES consumer texture on the same borrowed
EGLDisplay. It does not share texture names or require cross-API context sharing.
The helper never terminates the display or destroys caller-owned contexts.

The additive `release_timed` API performs one consumer wait with an explicit
timeout of0–5seconds (0 polls). Timeout retains its image/texture/handle for
retry. Existing default release remains unchanged. Injected tests use
`create_with_timed_ops`; older injected callbacks have no bounded timed-wait
contract and explicitly reject timed release. Flush queued libplacebo work
with `pl_gpu_flush` before calling release so the fence covers submitted draws.
Fatal host-only abandonment requires whole original EGLDisplay teardown;
context destruction alone does not invalidate display-owned EGLImages.

`EGL_OUTPUT_BRIDGE_RESULTS.json` remains the original historical source/binary
cohort unchanged. The separately pinned `EGL_OUTPUT_BRIDGE_TIMED_RESULTS.json`
captures the updated real helper/probe:64RGBA32F float bits and64RGBA16UI words
matched on the VM, actual timed consumer release and exact binding restoration
passed, peak48,140,288bytes/no swap/all memory events0. Kodi stayed active with
the same process/start identity; selected source/binary/collector/runtime pins
were stable. This remains two4x4 synthetic patterns, not Kodi playback or a
zero-copy/format-universality guarantee. Host UBSan tests cover zero poll,
timeout retention/retry and >5seconds atomic argument rejection.

Create requires the caller's current GLES context, a desktop GL producer context
on the same display, preserved EGL texture images and surfaceless capability.
It saves the exact API/context/draw/read binding, fences the producer, creates
the image, imports a GLES texture and restores the original binding. The current
GLES texture binding is restored as well. Each completion wait uses at most five
one-second fence waits; callers must impose an overall job timeout for driver
calls. This deliberately synchronous helper is not a frame queue or timing test.

The producer texture and its storage remain borrowed and must not be deleted,
respecified or overwritten until bridge release succeeds. Release fences GLES
consumer work before deleting the consumer texture and image. Timeout or cleanup
failure retains the handle for retry. Create requires an initially NULL handle;
an existing handle is rejected unchanged. A non-NULL handle returned with an
error owns partial resources and must be released, but must not be sampled.
Failure restoring the EGL binding is reported explicitly, not silently ignored.

Injected host lifecycle tests cover successful restoration, invalid capability,
producer/consumer wait failure, partial import, restore failure, owned-handle
rejection and cleanup without double deletion. They use UBSan but exercise no
actual graphics API. The real backend is separately compiled against SDK EGL.

## Actual synthetic checkpoint

[Saved evidence](EGL_OUTPUT_BRIDGE_RESULTS.json) records a bounded standalone
4x4 test on the existing VM. A desktop GL4.3 producer uploaded 64 dyadic float
components to RGBA32F and 64 public integer components to RGBA16UI. A GLES3.1
compute reader recovered all float bit patterns and integer values exactly.
Both producer and consumer fences completed and context/API/surface restoration
passed. Memory peak was 48,140,288 bytes under 512 MiB, zero job swap and zero
memory-limit/OOM events. Kodi PID/start identity and selected artifact pins
were unchanged. The standalone test owns and destroys only its own contexts
and display; it does not borrow Kodi's EGLDisplay or change its renderer.

This establishes only those two tiny tested patterns, not full-range precision,
4K pacing, real colour-output preservation, cross-thread lifetime, zero-copy
or playback performance. Actual Kodi integration must validate its output format,
orientation, frame/metadata association and consumer lifetime. The colour-only
API and reconstruction engine remain separate integration responsibilities.

Build the helper and probe together using the established strict C11 SDK flags,
`-fno-lto`, and `-lEGL`, under a single compiler CPU/512 MiB/zero swap. The probe
accepts only `/dev/dri/renderD128`. Run it inside an externally capped job with
a 30-second overall subprocess timeout; source alone does not enforce cgroups.

Primary resource-sharing contract:
[EGL 1.5](https://registry.khronos.org/EGL/specs/eglspec.1.5.pdf).
