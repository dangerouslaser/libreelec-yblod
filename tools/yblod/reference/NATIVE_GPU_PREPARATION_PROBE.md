# Explicit GPU preparation kernels

These experimental kernels translate the existing reference preparation, not
an assumed SK4 rule. They are not wired into Kodi. Hardware accuracy validation
is required before adoption; source review is not a rendered-pixel test.

`native_gpu_preparation_probe.comp` accepts normalized R16/RG16 P010 texture
words. Operation0 creates the MMR guide: independently rounded horizontal
`[1,2,1]/4` at each luma row, then a separately rounded average of row pairs.
Its normalized R16 output stores native guide codes, not Q6 words. Operations1
and2 apply caller-selected linear or cubic128 top-left-to-left chroma conversion;
explicit left input is identity. Native10 phase bounds and per-component bound
counts match the experimental reference. No texture filtering is used.

`native_gpu_el_scaling_probe.comp` implements the literal **informative** Annex-B
example after the explicit chroma phase conversion. Vertical and horizontal
dispatches remain separate, preserving per-pass rounding and unsigned16 bounds.
Vertical intermediates are R16UI/RG16UI native-code textures. Final outputs are
normalized P010 R16/RG16. A final code above1023 rejects the frame rather than
silently imposing an extra native-depth clamp. This is one declared software
GPU backend, not a requirement on future Intel/AMD hardware scaler backends.

Caller requirements:

- Validate format, texture dimensions, capabilities, non-aliasing and producer
  completion before dispatch; these shaders own no device/context/fence.
- Bind the declared typed images/samplers and select every route explicitly.
- Clear the status buffer before a frame; issue appropriate image/texture/SSBO
  barriers between passes, then wait for bounded completion and inspect status.
- **Discard all frame outputs if any failure bit is set.** Some other pixels
  may already have been written; this is not an atomic whole-frame transaction.
- Preserve texture storage until all consumers finish. Never present unverified
  or failed output, and retain the established playback fallback.

Preparation status uses bit1 for fractional P010 and bit2 for invalid geometry
or bindings. Scaling additionally uses bit4 for unsupported native10 overshoot
and bit8 for an intermediate sampler value above unsigned16 storage range.
Phase bounds statistics count components, not pixels. No media pixels, fitted
corrections, metadata-selected hidden rounding, or TV calibration are involved.
