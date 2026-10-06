# Genuine playback-context synthetic gate

The new runner exercises `native_playback_context.h`, not a manually assembled sequence of component diagnostics. It creates actual FFmpeg VAAPI AVFrames, uploads public synthetic P010 fixtures solely to construct the inputs, attaches expanded Dolby metadata using the actual patched FFmpeg layout, and supplies copied side-data bytes and explicit rational PTS associations.

The production context then performs borrowed VA enhancement scaling and import, declared guide/phase preparation, exact integer composition, explicit420 chroma expansion and the desktopGL-to-GLES output bridge. The runner reads the final GLES RGBA32F texture and checks every float bit against an independently prepared CPU oracle.

Two64×64 BL/32×32 EL fixtures use constant enhancement codes512 and513. Chroma metadata uses guide-sensitive MMR; the CPU preflight verifies guide influence and a nonzero residual that affects final12-bit output. There are32,768 expected RGBA float values across the two fixtures. Constant enhancement tests preservation through the declared scaler route, not interpolation accuracy on varying enhancement imagery.

Additional guards exercise rejected PTS association without decoder-reference changes, accepted actual AVFrame clones retained through completion, no new submission with outstanding work/output, restoration of exact EGL client API/context/draw/read bindings, and decoder-reference release only after the GLES consumer fence. A quarantined diagnostic fails while retaining its resources until process exit; it does not falsely claim device teardown while cloned FFmpeg frames still retain that device.

`--validate` prepares the complete native CPU oracle without VA/EGL/GPU calls. Structural host checks are not hardware evidence. The separate reviewed, pinned GPU collector requires the CPU gate first, a512MiB/no-swap cap, finite deadlines and unchanged Kodi/runtime identities. A tiny synthetic result is not sustained playback, full-size performance, native colour conversion or display conformance.

[Frozen actual GPU checkpoint](results/native-playback-context-synthetic-20261005r.json) passed all32,768 final GLES float-bit comparisons,12 restoration checks and decoder-reference/association checks. Peak memory63,389,696 bytes; swap and all memory events were zero, Kodi and pinned runtime unchanged.

After capturing that result, the production admission guard was tightened to require actual AVFrame buf[0] retained decoder storage. The report preserves the original tested executable, archives and source inventory, and separately identifies the later guard. Do not interpret the historical GPU evidence as a test of a rebuilt post-guard binary. Subsequent build-profile changes are likewise not retroactive GPU evidence.

[Separate host admission checkpoint](results/native-playback-frame-admission-host-20261005s.json) passed strict SDK compilation and three actual pure-helper checks in the matching SDK runtime: retained storage accepted, missing buf[0] rejected without mutating returned dimensions, restored storage accepted. It makes no VA/EGL/GPU calls and is not a GPU retest.
