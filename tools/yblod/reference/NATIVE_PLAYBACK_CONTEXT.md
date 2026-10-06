# Experimental native playback context

`native_playback_context.c/.h` is real orchestration code, not a capability
placeholder. On the renderer thread it owns a dedicated desktop GL context on
the borrowed GLES EGLDisplay, restores the exact client API/context/read/draw
binding, and never terminates the borrowed VA/EGL displays. Compiled shaders
arrive as caller-supplied bytes, not filesystem/Python dependencies.

The first route is paired VAAPI P010 native10 whole-code enhancement-enabled
input and INHERITED colour. It validates actual AVFrame format/hwcontext/device,
the decoder surface IDs, allocation/logical dimensions, BL/EL chroma hints and
exact BL best-effort / EL PTS using explicit decoder packet time bases. Copied
expanded metadata must be byte-equal to actual BL side data, bounded to1MiB;
its actual C converter and signed64 GPU width guard still decide admission.
Decoder frames are cloned on accepted submission, retaining real pool/device
references until consumer release—not reconstructed from filenames/timestamps.

The actual chain is VAAPI P010 EL scaling, per-layer DMA-BUF imports into
normalized R16/RG16 views, explicit BL guide/phase preparation, three-plane
integer reconstruction, bilinear-left YCC expansion into RGBA32F, and EGLImage
sibling import into GLES. RGBA contains reconstructed12-bit Y/Cb/Cr codes/4096
and alpha1, not colour-converted RGB. Original paired metadata then feeds the
separate inherited-colour-only renderer; no old reshape/NLQ should run again.
Whole-code gates reject fractional samples, not round them.

Every stage uses finite fences. An output is published only after complete
stage/error/association gates and binding restoration. New submission is
blocked while the output is outstanding. The renderer must flush its queued
libplacebo draws before timed consumer release; only then are sibling imports
deleted and decoded references released. Successful finish is not a whole-call
deadline guarantee: several individually bounded stages can execute in sequence.

Unsupported pre-dispatch contracts and completed rejected frames return idle
FALLBACK after cleanup. Uncertain submission/context/fence/restore failures
quarantine the transaction with all borrowed/owned storage retained. There is
initially no safe in-process VA device-reset protocol for retained FFmpeg pool
references; keep a quarantined decoded transaction until Kodi process exit and
disable further native use. Do not force vaTerminate then free its AVFrames.
The abandonment API rejects decoded references; host-only partial-create cleanup
requires externally confirmed whole VA/EGL display teardown.

The genuine paired-AVFrame synthetic context gate passed all 32,768 final GLES
float-bit comparisons, decoder-reference/association checks and 12 exact EGL
restoration checks. See [frozen synthetic evidence](results/native-playback-context-synthetic-20261005r.json)
and its explicit later buf[0] admission-guard boundary. This does not establish
installed Kodi presentation or full-film performance. No real-time playback,
conformance or SK4 matching claim is made here. Native colour, fractional Y416 policy and broader hardware/stream
coverage remain separate work. The optional19-check production ABI guard probe
tests invalid arguments without driver work; it is not hardware evidence.

The19-check probe links the actual combined native archive and passed with
the matching SDK loader/libraries. Plain Ollie lacked `libavutil.so.61`, so
that launch could not execute; it is not reported as a passed host replay.
Optional test variables `YB_NATIVE_PLAYBACK_CONTEXT_LOADER` and
`YB_NATIVE_PLAYBACK_CONTEXT_LIBRARY_PATH` must be supplied together when
replaying an SDK binary outside a matching LibreELEC runtime. Use the SDK's
intended build-container mounts: its staged library symlinks can depend on
`/build`, so passing the host-side sysroot path alone may still fail to load.
The actual Python guard replay passed inside that capped SDK container.

## Reproducing the opt-in build and runtime selection

Both selections default OFF. Building the feature does not enable it at runtime,
and setting the runtime variable cannot add it to a Kodi binary built without it.
From the repository root, a conservative build request is:

```bash
YBLOD_NATIVE_RECONSTRUCTION=1 BUILD_MEMORY=4g BUILD_JOBS=1 \
  tools/yblod/build.sh native-test
```

The wrapper now forwards the build opt-in into Docker. BUILD_MEMORY caps the
container; equal memory/memory-swap limits prohibit container swap. BUILD_JOBS
sets the make-concurrency attempts. Defaults remain 12g and "7 5 3"; the wrapper
retains its existing THREADCOUNT=4 setting, so this is not a new one-thread CPU
cap. Choose a host-appropriate cap and expect a build to fail safely if it is too
small. Do not run this alongside another heavy build on Ollie.

The 512 MiB/no-swap evidence applies to isolated diagnostic jobs. The actual
incremental Kodi candidate rebuild uses a separate 4 GiB/no-swap, single-job gate.
The command above is a reproducible full-image entry point, not a claim that a
complete opt-in `make image` run has been tested or that every image-building
stage fits 4 GiB.

After installing a reviewed opt-in candidate, enable the runtime path in Kodi's
service environment. On LibreELEC, create
`/storage/.config/system.d/kodi.service.d/90-yblod-native.conf` with:

```ini
[Service]
Environment=DVBRIDGE_NATIVE_RECONSTRUCTION=1
```

Then, when ready to interrupt playback:

```bash
systemctl daemon-reload
systemctl restart kodi.service
```

To disable it, change that Environment value to 0 and reload/restart again. This
leaves the existing renderer available. Verify the native-path logs actually
show new-engine frames presented: fallback-only playback is not a successful
native playback test. A real connected HDMI display is required for the actual
Kodi presentation test; turn the TV on when checking display capabilities and
output. Synthetic surfaceless GPU gates do not establish presentation readiness
with a disconnected or sleeping display.
