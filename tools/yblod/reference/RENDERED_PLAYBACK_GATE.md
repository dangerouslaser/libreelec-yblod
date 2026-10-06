# Experimental rendered-playback gate

Current target: an opt-in Kodi candidate that actually presents pixels reconstructed
by the experimental engine, retaining the existing renderer as explicit fallback.
A side-by-side diagnostic while the old renderer presents is useful but does not
complete this target.

## Ordered work, with parallel independent tasks

1. Reduce generic integer shader temporary lifetimes without changing arithmetic.
   Synthetic exactness, compiler inspection, then complete prepared-frame gates.
2. Establish exact packed Y416 graphics access. Compare upload, VA readback and
   imported-word recovery separately; preserve twelve-bit RT versus sixteen-bit
   storage distinction. P01024-word access already passed.
3. Build a live metadata/layer adapter at CDVBridgeGLES Prepare/PrepareHardware.
   Preserve paired frame identity, sampling geometry, metadata guards and reset.
4. Implement a declared input precision route. Whole-code P010 and fractional
   Q6/Y416 must not be silently interchanged. The existing literal fractional
   probe is hypothetical, not a selected Dolby production rule.
5. Provide a colour-only/output path after reconstruction. Feeding reconstructed
   pixels through the original DV reshaper with the original metadata would
   reconstruct twice. Retain tested colour rules and explicit output transport.
6. Validate cross-context texture ownership/completion, fallback and presentation
   commit/reset behavior, with bounded resources.
7. Build Kodi on Ollie, publish source, install/restart the VM candidate and test
   1917/Saving Private Ryan. Verify the new backend actually ran; fallback-only
   playback is not a successful engine-playback test.

## Safety and acceptance

- GPU width guards remain; valid but unsupported signed128 metadata must not wrap.
- Fractional samples never undergo an undeclared rounding or truncation.
- No arbitrary source clipping or licensed-player fitted offsets.
- Default existing playback remains available as explicit fallback.
- Private media/RPU/pixels never enter public reports; synthetic fixtures may.
- Heavy compilation uses one CPU/512MiB/no job swap; GPU jobs are sequential and
  capped512MiB/no swap. All GPU allocations are not bounded by charged-memory
  measurements alone.
- Source and evidence are committed/pushed incrementally.
- Only stop for user direction when a genuine required decision or external
  blocker cannot be resolved safely. Optional diagnostic phases are not stops.

## Known evidence

P010 shared-surface shader recovery passed24publicsyntheticstoredwords.
Y416 exported native format was external-texture-only. The explicit AB48 packed
reinterpretation recovered all64syntheticwords exactly versus VA readback;
upload versus VA also matched. This is storage-access evidence, not proof of
sixteen-bit processing or a selected fractional reconstruction policy.
The generic integer diagnostic showed SIMD16 register allocation failure; SIMD8
has1582instructions/128GRF and42:14static scratch/spill/fill counters. Those
counters mix local scratch and allocator activity, not runtime transfers.
Recent copying/wait/table tweaks did not establish performance gains.

The scalar-streamed integer candidate subsequently passed all8512syntheticstage
checks and compiled as SIMD16 with zero reported scratch accesses. Balanced
prepared-frame comparisons also passed complete stage checks; published timing
details are separate from playback speed. The baseline remains unchanged.

The first opt-in rendered candidate may use a declared whole-code P010 route,
falling back for fractional Y416. This avoids making selection of a hypothetical
fractional rule a prerequisite for the first playback test. Live GPU sampling,
colour-only output and desktopGL/GLES ownership still require implementations.

This checklist is a work plan, not a claim that a rendered candidate is ready
or that the remaining work has a reliable calendar estimate.
