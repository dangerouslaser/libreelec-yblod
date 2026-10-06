# Live metadata adapter for the first opt-in compositor

`native_playback_metadata.c/.h` calls the existing real C FFmpeg integer
adapter, optional native colour adapter and conservative GPU width guard. Input
is borrowed decoder-expanded side data compiled against the matching patched
FFmpeg header, not an offline blob or Python coefficients. Success owns copied
configurations and frame declarations. Failures preserve the destination.

The first route requires paired BL/EL timestamps (exact rational equality),
matching nonzero frame/metadata/EL/guide identities, explicit guide preparation
and EL scaling identities, even full-raster dimensions no greater than
3840x2160, native10 whole input codes, full-sized prepared EL and quarter-sized
guide, residual-enabled reconstruction12 output. Producer spatial declarations
must match the metadata. Unsupported arithmetic width, fractional values or
preparation route reject rather than silently changing arithmetic.

Tokens and preparation declarations remain caller assertions, not authentication
or evidence that a producer applied the stated filter. The compositor must
still validate actual GL formats, sample values and frame completion. Retain
decoded surfaces and borrowed textures through its consumer completion.

Colour route is explicit:

- `YB_PLAYBACK_COLOUR_INHERITED`: target NULL, source-DM declaration0, zero
  native colour configuration and has_native_colour0. The separately reviewed
  inherited colour-only renderer validates colour metadata later, without
  repeating mapping/NLQ. This does not fabricate known uncompressed DM history.
- `YB_PLAYBACK_COLOUR_NATIVE`: explicit target and known source-DM history;
  invokes the native colour converter and owns its copied configuration.

There is no default route or automatic fallback between these two colour modes.
Kodi policy decides whether a rejected experimental frame uses the existing
renderer; this adapter itself does not change playback.

The real patched-FFmpeg synthetic fixture tests cover22 cases: both owned
colour routes after releasing source data, pairing/geometry/preparation/fractional
failures, malformed metadata, explicit target guards, luma-MMR rejection and
valid native128 metadata rejected by the signed64 GPU envelope. The optional
replay uses `YB_PLAYBACK_METADATA_PROBE` pointing to the matching SDK binary;
without it those tests skip rather than claiming a real adapter was executed.
Strict C11 SDK build and22-case replay passed. No GPU, media or live Kodi calls
are part of this checkpoint.
