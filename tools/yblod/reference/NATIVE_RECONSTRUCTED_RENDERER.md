# Opt-in reconstructed-input renderer entry point

`kodi-9999-yblod-06-native-reconstructed-input.patch` adds
`dvbridge_render_reconstructed_rgb` without switching any existing caller.
Normal RGB, HDR10 and packed routes retain their original behavior.

The new entry point retains the original paired BL/EL frame for validation,
metadata, packet preparation, active area and presentation transaction. Its
pixel source is instead a borrowed, source-sized, unrotated RGBA32F texture:
Y/Cb/Cr reconstructed12-bit codes divided by4096, alpha1. Colour-plane expansion,
pixel ranges, alpha1, producer completion and lifetime remain caller obligations.

It disables all three old reshaping components and NLQ, and removes the old EL
pixel source. This prevents reconstructing the new engine's pixels twice while
retaining the **inherited colour conversion and transport** for a first restricted
playback candidate. It is not adoption of the separate native GPU colour stage,
nor a claim of Dolby conformance or licensed-player calibration.

Only sampleable four-component32-bit floating textures matching source geometry
are accepted; rotated sources are rejected rather than guessing orientation.
Alpha interpretation is explicitly independent. New early validation failures
leave no pending presentation candidate; null input clears any previous one.
Presentation commit remains the caller's responsibility after actual display.

Checkpoint: the patch applies without fuzz to the current patched Kodi22 source.
The modified actual C renderer compiles with the matching LibreELEC SDK using
`-std=c11 -O2 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off`, one CPU,
512MiB and no job swap. Two source/patch contract tests pass. These are compile
and applicability checks, **not** rendered-pixel or playback tests. No installed
Kodi binary or playback default has changed.
