# Experimental FP32 playback integration

The existing integer reconstruction engine remains the default and the comparison
reference. Set `DVBRIDGE_NATIVE_FP32=1` before creating a native playback context
to request the experimental libplacebo hybrid composer. The setting is read once
per context; changing it requires creating a new context. Native playback itself
still requires its existing opt-in and capability/admission checks.

## What changes

Actual libplacebo `pl_shader_dovi_reshape` generates the base-layer reshaping
functions. Our dedicated OpenGL compute context executes those functions on the
GPU. The experimental adapter preserves the native binary sample/pivot domain
and explicitly matches the integer engine's output bounds; it does not blindly
adopt a different normalization or output-clamping convention.

Integer sample extraction, enhancement-layer nonlinear quantization/correction,
native Q16 quantization before correction, final output quantization, existing
guide/chroma preparation, and colour expansion remain in the surrounding engine.
Floating-point base-layer evaluation can still differ from the integer reference;
equivalent sampling and limits do not promise identical intermediate rounding.

VA-API continues to perform enhancement-layer scaling using Intel's supported
video-processing operation. The libplacebo equations are programmable GPU work,
not a new QuickSync/VA-API Dolby-composer operation. This integration introduces
no new decoder, VA display, EGL display, or libplacebo GPU context.

## Shader cache and metadata updates

The composer caches two completed shader-topology entries. Topology includes
each component's pivot count, segment method, and polynomial/MMR order.
Numerical coefficient and pivot changes update CPU-decoded float uniforms
without recompiling a cached topology. Native integer metadata remains present
for enhancement correction and shader-side validation.

A new topology generates GLSL in memory and compiles synchronously. Replacement
creates the candidate before evicting a cached entry, temporarily retaining a
third hybrid backend. Normal operation retains no more than two hybrid entries,
plus the integer fallback backend. These are not additional decoded-frame pools.

Measure first-frame/new-topology generation and JIT latency separately from warm
reconstruction timing. A warm shader speedup does not prove the complete playback
path is faster, nor that all films avoid compilation hitches.

## Safety and fallback

The opt-in wrapper retains the existing dedicated-current-context, borrowed-input,
frame-error, fence, and finite-wait contracts. Producer completion is not consumer
completion: previous output consumers must finish and release their textures
before another submit, cache eviction, or destruction. The playback context's
existing output-release state machine enforces this requirement.

Unsupported generation or a rejected shader creation with no retained handle may
use the integer reference. Uncertain GL work or retained cleanup failures never
trigger an unsafe alternate submission: owned handles are retained for existing
quarantine/context-teardown handling. No fences or ownership checks are removed
for performance.

## Observability and comparisons

With existing native diagnostics enabled, periodic `DVBridge native composer:`
records report the latest accepted route, accepted FP32/integer submissions,
cache hits/misses, generation failures, and shader-creation failures. Counters
saturate rather than wrap. They are CPU-only, same-owner-thread diagnostics.
Default integer-only contexts report zero wrapper counters. Accepted submissions
are not unique displayed frames; `fp32_selected` reports an actual accepted
route rather than merely echoing the environment setting.

Compare accuracy against the retained integer implementation using complete
plane outputs, including maximum code difference, differing-value counts, and
spatial error patterns. Compare performance using equivalent content, settings,
timing windows, and repeated/reversed runs, reporting both warm work and cold
topology changes. Keep fallback and resource-limit evidence with the measurements.

This document describes the integration, not a completed playback qualification.
It makes no Dolby conformance, fixed-point bit-exactness, universal one-code
accuracy, or match-to-licensed-hardware claim. SK4 captures remain an independent
comparison rather than a target for unexplained image tuning.
