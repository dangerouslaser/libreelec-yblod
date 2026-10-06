Opt-in native colour handoff without redundant original-layer imports
===================================================================

Default: DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT unset or 0 retains the existing route.
Experimental: set it to exactly 1, with native reconstruction enabled, to use
the dedicated validated metadata-only colour entry. Other values do not enable
it. This does not fuse colour shaders or remove the RGBA32F YCC intermediate.

After successful native admission/completion and frame-ID validation, the new
entry passes explicit geometry, PTS, native VAAPI/P010 admission and output-ID
evidence instead of importing enhancement DMA buffers and wrapping original BL
and EL textures that the reconstructed colour route never samples. There are
no dummy textures. Native producer ownership of decoded frame references and
its output texture continues until the existing consumer release fence. The
same reconstructed texture, reshaping/NLQ bypass, inherited colour conversion,
active-area handling, packet serializer and presentation commit remain shared.
Legacy APIs, capture, direct packed and non-native fallback are not switched.

Source pins describe the actual Kodi22.0rc1-Piers build tree with existing YBLOD
native integration and shutdown patches. This patch does not apply to pristine
upstream Kodi. The baseline and modified content hashes support reviewed
reproduction; apply through the repository's Kodi patch workflow after checking
the source tree matches. No CMake change is required; install the added header.

CPU validation test:
  cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
     -I/path/to/patched-kodi/tools/dvbridge test_native_colour_association.c \
     -o /path/to/private-output/test-native-colour-association
The test requires no GPU/media and rejects missing proof, invalid geometry,
hardware admission/depth/rotation, mismatched or missing frame IDs, mismatched
raw/presentation PTS, invalid timebase and nonfinite presentation timestamps.

The synthetic GPU comparison is native_colour_entry_compare_probe.c. Build
against the patched bridge and the same libplacebo/FFmpeg versions as Kodi:
  cc -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -fno-fast-math \
     -ffp-contract=off -I/path/to/patched-kodi/tools/dvbridge \
     native_colour_entry_compare_probe.c \
     /path/to/patched-kodi/tools/dvbridge/dvbridge_render.c \
     /path/to/patched-kodi/tools/dvbridge/dvbridge_core.c \
     /path/to/patched-kodi/tools/dvbridge/dvbridge_placebo.c \
     -lplacebo -lavutil -lavcodec -lEGL -lGLESv2 -lm -o /private/output/probe
Run --metadata-only first; it does not access the GPU. The GPU arguments are
NODE EXCLUSIVE_CHECKPOINT [WIDTH HEIGHT], default 64x64 and optionally up to
3840x2160. Run only while playback is stopped, under the documented 512 MiB/
zero-swap/one-CPU diagnostic guard. The checkpoint is about 133 MB, requires
fresh storage, and is reproducible synthetic data. Keep debug stderr private.

Required qualification before a quality/performance claim:
1. Strict compilation of C renderer and Kodi C++ both native-enabled/disabled.
2. Same-renderer old/new sequential GPU colour output comparison, full image
   row-streamed bit comparison, with identical reconstructed pixels/RPU/geometry.
   Preserve metadata packet fields/bytes and active-area margins before the
   next render invalidates the old candidate. Include invalid-entry cases.
3. Before/after playback ABBA on the same binary: FP32 native selected on both
   routes, same title/start/time window, diagnostics/environment/hardware and
   output settings, flag0 vsflag1. Record actual presented route in logs.
4. Compare memory events/peak, CPU load, dropped/missed frames, native stage
   counters and the additional colour handoff counters, not just nominal FPS.

DVBRIDGE_NATIVE_DIAGNOSTICS=1 enables cumulative colour handoff wall/thread-CPU
time per successful prepared call. The window starts before reconstructed
libplacebo wrap and includes Prepare, pl_gpu_flush and wrapper/DMA destruction;
it ends BEFORE native consumer release. Existing native counters still record
that release separately. Four clock reads per prepared frame are diagnostic
overhead shared by both comparison routes. Counters reset per renderer reset/
native context; clock/overflow/preparation failure makes validity sticky false.
Calls are not unique displayed frames or GPU-exclusive kernel timings.

Presented logs distinguish colour_imports=metadata-only from
original-bl-el-reimport. Do not infer route execution just from the flag.
This change has no accuracy claim until the GPU/output gates pass. It should
not change pixel math; any difference must be investigated, not tuned away.
No private film data, Dolby coefficients, captured pixels or media hashes are
included here. Strict SDK compilation passed for the C renderer and both
native-enabled and non-native Kodi C++ configurations (377,335,808-byte scoped
peak under 512 MiB; no memory events or swap). Synthetic GPU old/new comparisons
passed for 64x64, 1920x1080 and 3840x2160 inputs, checking the complete 4K RGB
image, packets and margins. These are one synthetic metadata fixture, not film
frames or display conformance. Real playback performance remains unqualified.
