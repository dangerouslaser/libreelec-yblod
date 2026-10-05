# Proposed native stage boundary

Design proposal, not an implemented playback backend. Existing arithmetic and
diagnostic APIs remain unchanged. No Kodi integration, fractional EL rule,
hardware filter, output target or HDMI default is selected here.

## Two deliberately different input contracts

`PREPARED_WHOLE_CODES` means native 8/10-bit integer planar BL and EL, already
aligned to the same reconstruction grid, with an explicit luma guide for chroma
MMR. The preparation owner declares geometry, frame association and preparation
method. It is the contract supported by `yb_process_chunk` today. A disabled
enhancement layer is explicit and requires NULL EL/NLQ arguments; missing or
invalid data is never a base-only fallback.

`RAW_Y416_DIAGNOSTIC` means stable CPU-readable LE U/Y/V/A 16-bit storage with
declared pitch and native10/Q6 colour significance. The unpacker preserves every
word; alpha remains a separate uninterpreted channel. An explicit sampling
contract may return exact raw/native/normalized rationals. This branch stops
before inverse NLQ. It cannot call the whole-code composer, even when a particular
buffer happens to contain only multiples of 64. Selecting a transport quantizer
or accepting fractional EL requires a separately reviewed contract, not a cast,
right shift, nominal-depth clamp or automatic precision-policy choice.

The raw normalization divisor and interpolation operator are mandatory
diagnostic inputs. Bilinear is not the informative Annex B resampler. Annex B
is a separate coded-integer diagnostic and does not establish a hardware filter.

## Proposed caller-owned C interface

Names below are proposals, not exported symbols:

```c
yb_pipeline_init(context, frame_descriptor, provenance, mapping,
                 component_nlq_or_null, colour_parameters_or_null);
yb_pipeline_compose_integer_chunk(context, component, global_start,
                                  y_guide, cb, cr, el_or_null, count, outputs);
yb_pipeline_colour_chunk(context, global_start, expanded_triplets,
                         count, explicit_strides, outputs);
yb_pipeline_inspect_raw_chunk(context, surface, region, unpack_outputs);
yb_pipeline_sample_raw(context, complete_plane, sampling_contract,
                       queries, count, rational_outputs);
yb_pipeline_finish(context, completion);
yb_pipeline_reset(context);
```

The descriptor includes version/size, input kind, frame width/height, component
extents, BL/EL/output depths, explicit enhancement-enabled flag, frame identity
token, and named preparation/guide/chroma-expansion contracts. No enum has an
implicit default. Colour conversion requires explicit 12-bit reconstructed
inputs, source/target matrices and offsets, PQ policy and code scale; the current
colour API does not accept the composer's 10-bit output without a new declared
adapter. Colour input expansion is separate from enhancement sampling.

Initialization copies validated arithmetic metadata into fixed-size context
storage and compiles colour configuration via `yb_colour_init`. It does not
retain caller configuration pointers or accept a caller-forged compiled inverse.
Also check global mapper/EL denominator agreement and depth constraints, rather
than relying only on isolated stage validators. A context is single-frame,
single-thread-owned and immutable except for bounded progress/error counters.
Reset invalidates it but never frees caller buffers or an external device handle.
Concurrent calls or configuration mutation are unsupported.

Use component-specific monotone positions/counts to reject gaps, duplicates,
overrun and out-of-order chunks. Raw query batches do not imply frame coverage;
their completion kind is explicitly diagnostic. `finish` accepts composition
only after all required component extents are consumed; colour completion needs
its separately declared full-raster extent. There is no catch-all “pipeline
verified” flag based solely on arithmetic or diagnostic completion.

Statuses should distinguish invalid descriptor/configuration, frame association
failure, unsupported input contract, fractional-policy-required, producer-not-
ready, invalid/aliased buffer, stage failure, count mismatch and incomplete
frame. Preserve originating stage/status. No fallback, stale-frame reuse or
automatic retry with a different format. All validation occurs before a stage
call; failed chunks leave their destinations and progress counters unchanged.
Successful earlier chunks remain partial output if a later chunk fails. The
frame owner must not publish/present them as a completed frame. This is not a
whole-frame atomic-write guarantee.

## Ownership and bounded memory

The context owns copied metadata and counters, not decoded surfaces, fences,
files, GPU resources, TV configuration or decoded RPU lifetime. Buffers are
borrowed for each call with explicit capacities/strides and must remain stable,
coherent and accessible until return. A CPU pointer cannot prove producer fence
completion. Device import/download and synchronization belong to the backend.

Chunks are capped at 65536 samples. Caller workspaces and output allocations
have declared extents and disjointness rules. Integer composition has no
whole-frame working array; current colour processing additionally allocates a
bounded temporary result array (about 6.5 MiB at the maximum chunk on the tested
ABI). A reusable colour workspace would be a later tested optimization, not a
claim about the present implementation.

Lossless unpacking is row-bounded. The existing raw sampler, however, requires a
complete borrowed colour plane: a stripe must not become a replicated image
edge. A 3840×2160 u16 plane is 16,588,800 bytes. Sampling can borrow an existing
complete plane; this proposal does not require copying every plane into the
context or pretend the current sampler supports arbitrary halos. A future
global-coordinate/halo adapter must prove equivalence before replacing that
contract. The Annex B diagnostic instead uses complete borrowed coded input,
full-native-width row scratch and global bounded output rectangles.

Buffer footprints are not process/cgroup peak-memory guarantees. GPU imports,
driver allocations, page cache and retained evidence must be budgeted separately.

## Provenance, hardware offload and output ownership

Provenance records implementation/build/ABI identifiers and source/binary hashes;
opaque frame/RPU/source-association digests; preparation, scaling, grid, sampling
and precision-contract identifiers; explicit stage configurations; and actual
backend invocation evidence where available. Caller-supplied tags are claims,
not authentication of pixels, decoder state or hardware execution. Public
reports expose safe digests/aggregate facts, not film samples or extracted RPU/DM
payloads. Runtime ABI sizes must agree before using a separately built library.

QSV and AMD hardware scaling stay upstream and backend-owned. Preserve actual
surface format, coded-versus-fractional significance, coordinates, metadata
association and synchronization across offload; do not force a CPU scaler or
pretend a raw Y416 surface already meets the whole-code composer contract.

Active-area handling, transport subsampling/packing, TV-led metadata carriage,
HDMI signalling and presentation remain downstream-owned. The present standalone
colour bridge performs declared left chroma expansion, colour conversion and
diagnostic unembedded tunnel packing; it does not supply complete TV-led output.
Reconstruction limits come from reconstruction metadata, not TV/EDID capability.
No display capability or matching capture may silently rewrite reconstruction
parameters or choose EL precision. Missing downstream metadata/signalling must
not be labelled a completed TV-led pipeline.

## Synthetic acceptance gates before implementation/integration

- Initialize from caller metadata, then mutate the originals: copied context
  behavior must remain unchanged; reject malformed/unsupported versions and
  ABI size mismatches before touching outputs.
- Compare whole-code chunk stages against independent prepared-frame fixtures,
  including polynomial/MMR, binding NLQ caps, wide signed corrections, disabled
  EL and final 10/12-bit output. Require each stage, not only the final picture.
- Reject raw-Y416 composition for both fractional and all-integer-looking words;
  preserve raw65535, alpha and low bits in diagnostic dispatch. Explicit half-
  pixel `[32768,32784]` must return raw32776 without selecting an NLQ quantizer.
- Reject mismatched frame/provenance association, wrong component extents,
  duplicate/skipped chunks, late-invalid codes, aliases and insufficient buffers;
  preserve failed-call destinations/counters. `finish` must reject partial frames.
- Exercise producer-not-ready and stale/reused contexts using synthetic tokens;
  such tests validate control flow, not actual DMA-fence correctness.
- Require explicit colour configuration/expansion and native-vs-independent
  colour comparisons; reject 10-bit reconstructed input at this current bridge.
- Run strict host/target builds and sanitizer tests. Existing
  `native_sampling_smoke.c` exercises unpacking, explicit sampling and independent
  Annex B literals in pure C, but is not acceptance of this unimplemented context
  or a complete playback pipeline. No GPU/TV job is required for these CPU gates.

First implementation should only add the descriptor/context validator and
explicit whole-code dispatch plus failure tests. Raw inspection stays diagnostic;
colour/whole-frame publication and device ownership are separate reviewed steps.

## Staged initial adapter

`native_integration_probe.c/.h` now implement a **standalone diagnostic subset**
for review: copied fixed-size configuration/provenance tokens, whole-code chunk
dispatch, complete-plane raw sampling, strict count checks and explicit
finalization/reset. The existing unpacker stays a separate borrowed-buffer API;
colour, device readiness and source authentication are not integrated. The
descriptor's native depths derive from validated mapping/NLQ configurations;
enabled component NLQ depths must agree and share the mapper denominator.

Actual symbols are `yb_integration_init`, `yb_integration_integer`,
`yb_integration_raw`, `yb_integration_finish` and `yb_integration_reset`.
Whole-code frames require even 4:2:0 dimensions and exact Y/Cb/Cr counts. Raw
diagnostics may use odd dimensions and report queried-sample totals only.
Completion kinds are `YB_ARITHMETIC_FRAME_COMPLETE` and
`YB_DIAGNOSTIC_SESSION_COMPLETE`, neither playback completion. Stage errors are
currently categorized as `YB_INTEGRATION_STAGE`; this subset does not yet expose
the originating stage's detailed numeric status. Context integrity is a caller
obligation: the initialization marker is not a security boundary against forged
or edited structures. ABI queries are `yb_integration_abi_version()` (version1)
and `yb_integration_sizeof_{descriptor,context,completion,sampling_contract}()`.
Bindings must check these before calling a separately built library.
Producer-readiness tokens remain a future integration requirement; initialized
context status is not evidence of a signalled producer fence. Caller frame and
provenance tokens may contain any 32 bytes, including zeros: equality establishes
only agreement of caller assertions, not source authentication.

`python3 -m unittest -v test_native_integration_probe` compiles the C adapter with
strict warnings in a fresh temporary directory. Nine CPU tests cover copied
metadata, literal stages, binding limits, disabled EL, exact frame/session counts,
half-pixel raw precision/overshoot, wrong routes, late invalid data, count overflow,
frame-token mismatch, repeated finalization, aliases, reset, ABI sizes,
null/misaligned pointers and forged wrapping addresses rejected before
dereference. Enabled composition refuses a NULL enhancement pointer without
altering outputs or progress. Pointer-span checks cannot prove allocation
accessibility, lifetime or synchronization. Optional
`YB_INTEGRATION_TEST_CFLAGS` adds sanitizer flags to the temporary test build.
No GPU, Kodi, CMake core, HDMI or existing arithmetic-source changes accompany it.

All nine adapter tests also passed on Linux/Ollie with UndefinedBehaviorSanitizer
and recovery disabled, in a 512 MiB scope with job swap disabled (0.328 seconds
reported test runtime). This validates synthetic CPU boundaries on that build;
no process/cgroup peak-memory measurement, frame-rate result or playback claim
is inferred from this capped test execution.
