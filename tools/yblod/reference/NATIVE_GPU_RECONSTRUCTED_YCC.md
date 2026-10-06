# Reconstructed chroma expansion

`engine/experimental/native_gpu_reconstructed_ycc.comp` converts three integer
reconstruction textures into a full-size RGBA32F Y/Cb/Cr texture. This is not RGB
colour conversion. The first candidate explicitly uses the existing reference
policy `bilinear-left-diagnostic`: chroma centres are at x=2*i, y=2*j+0.5,
with border extension. No chroma rounding occurs. Twelve-bit codes are divided
by 4096, with alpha set to one, for the inherited colour-only renderer.

The sampling contract and 12-bit output declaration are mandatory uniforms.
Invalid dimensions or sampled codes set a whole-frame error flag. The owner
must inspect it after GPU completion and discard the entire output on failure;
individual partial writes must never be presented. The wrapper must validate
R16UI inputs, default integer swizzles, non-aliasing output and frame identity.

This is an explicit experimental sampling policy, not a universal Dolby rule.
Source/policy tests and GLSL compiler validation do not establish hardware
execution, playback performance or conformance. A separate hardware oracle and
production wrapper are still required before adopting this stage.
