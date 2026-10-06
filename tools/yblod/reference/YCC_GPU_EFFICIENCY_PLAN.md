# GPU efficiency measurement plan

The current faster path plays the tested scenes smoothly. Further optimisation
will use that working build as the control and preserve its sampling, precision
and resource-completion checks. The first candidate changes colour-sampling
coordinate calculations, not colour policy or Dolby reconstruction.

## Current costs

The native engine reconstructs the original 4:2:0 planes, expands them into a
full-size RGBA32F YCC texture, and passes that texture to the inherited
libplacebo colour/render stage. The experimental standalone native colour probe
is not the live Kodi colour implementation.

At 3840 by 2160, the expansion writes 132,710,400 bytes. One subsequent logical
read brings the total to 265,420,800 bytes per frame, or about 6.36 GB/s at
23.976 frames/s. This is calculated logical traffic, not measured DRAM traffic;
caching, compression and other stages change the physical traffic.

The expansion also performs nine logical texture fetches per pixel: one luma
and four for each chroma component. Texture caching can reuse neighbouring
samples. A full-image intermediate may therefore be a useful future target,
but removing it requires consumer integration and full-output verification.
Lowering precision is not part of this experiment.

## First candidate

`native_gpu_reconstructed_ycc_integer_coords.comp` computes sampling coordinates
once per pixel with integer parity rather than constructing them twice with
float/floor expressions. All 8,294,400 4K coordinate tuples match the existing
equations, including borders. Texture fetches, interpolation order, clamps,
error flags and RGBA32F output remain unchanged.

The companion `native_gpu_reconstructed_ycc_bit_coords.comp` uses shifts and
parity for the same coordinates, avoiding signed division. The existing 8 by 8
dispatch geometry is unchanged in both variants.

The compiler may already perform equivalent optimisation. There is no speedup
claim until GPU measurements show a repeatable benefit.

## Qualification

1. Complete the remaining matched playback windows and stop/restart checks on
   the same working binary.
2. Use diagnostic-only GPU elapsed queries around reconstruction and expansion.
   Collect results after existing completion checks, without adding production
   waits or removing fences. GPU elapsed intervals can include preemption and
   idle time; they are not exclusive kernel cycles.
3. Require exact float-bit output against the independent expansion oracle,
   including borders and error cases. Use bounded readback, not duplicate
   full-size float arrays.
4. Compare control/candidate/control order on the same inputs and hardware,
   with bounded warmups and samples and no simultaneous movie playback.
5. Integrate only a repeatable improvement, then repeat matched real playback
   and output comparisons. If the candidate is neutral or slower, keep the
   working control.

Diagnostics remain capped at 512 MiB, no extra swap and one CPU. That cap does
not apply to the Kodi playback service. Private film frames and Dolby metadata
are not included in the repository.

## Source locations

- `engine/experimental/native_gpu_reconstructed_ycc.comp`
- `engine/experimental/native_gpu_ycc_backend.c`
- `engine/experimental/native_playback_context.c`
- `engine/experimental/native_egl_output_bridge.c`

See [current playback evidence](FP32_PLAYBACK_COMPARISON.md),
[expanded arithmetic accuracy](EXPANDED_FP32_ACCURACY.md) and
[paired saved SK4 differences](PAIRED_FP32_SK4_FRAME1943_RESULTS.md).
