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

Current sources have strict SDK object builds; separate scaler, preparation,
composer/YCC and EGL sibling gates do not yet prove this complete live chain.
The genuine paired-AVFrame synthetic runner and actual Kodi opt-in hook/build
are subsequent gates. No real-time playback, conformance or SK4 matching claim
is made here. Native colour, fractional Y416 policy and broader hardware/stream
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
