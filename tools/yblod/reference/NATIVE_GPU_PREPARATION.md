# Reusable experimental GPU guide/phase preparation API

`engine/experimental/native_gpu_preparation.c/.h` wraps the measured guide/phase
shader as a caller-context asynchronous API. This is a production-integration
candidate, not a claim that the live pipeline is already wired or tested.

The caller owns a dedicated desktop GL4.3+ context, loader and current-context
callback. Every call verifies the exact captured context. No EGL display or
context is created/destroyed; bindings are intentionally clobbered within that
dedicated context. Never invoke directly in Kodi's GLES rendering context.

The explicit plan borrows normalized R16 BL luma and RG16 BL chroma P010 Q6
views. Dimensions are positive/even, at most 3840×2160. Caller supplies frame
identity, guide/phase recipe IDs, left/top-left location and linear/cubic128
phase choice. IDs assert provenance, not authentication. No display-dependent
decision, metadata inference, enhancement scaling or hidden CPU fallback occurs.

Submit queues guide and chroma-phase kernels, then one fence, without plane
readbacks. Finish waits at most five seconds and reads only the three status
words. PENDING and unfenced/failed queued work prohibit destruction or input
reuse. Successful output owns one R16/native10 guide and RG16/P010 phase plane,
with frame/recipe IDs and below/above phase clip counters. Frame error rejects
all output. Caller must finish downstream consumers before the next valid
submit can overwrite the single output set.

Destroy requires the same current context and no pending work. Failed deletion
retains a closing handle for retry, with successfully deleted names cleared.
Destroyed-context abandonment is explicit and performs no GL calls.

Current evidence: strict SDK compilation and five pure CPU guard/source tests,
also under UBSan, pass. Actual wrapper execution is saved in
`results/native-gpu-preparation-api-synthetic-20261005p.json`: 304 words and
33 status fields match independent/native oracles; 11 pending double-submits
and 11 pending-destroy attempts correctly return BUSY and retain the handle.
Frame/recipe tokens, finite finish and cleanup pass on Intel TGL. These tests
do not inject context loss or driver failures; imported live surfaces,
full-frame performance and playback remain required gates before adoption.

## Historical 1917 header audit

A previously verified, decoder-extracted 1917 fixture reports BL 3840×2160
and EL 1920×1080, both top-left chroma. Its RPU identifies Profile 7/FEL,
EL spatial resampling enabled, BL spatial resampling disabled and no explicit
chroma-filter payload. This is a historical fixture audit, not evidence of
the current live hardware decoder's AVFrame properties; no pixels or private
fixture paths/hashes are published here.

[Dolby's public profile specification](https://ott.dolby.com/OnDelKits/Dolby_Vision_Online_Delivery_Kit/v1/Documentation/Specs/Visio_Profiles/help_files/topics/c_dovi_profiles.html)
lists top-left VUI chroma location for both Profile 7 layers. The RPU's EL
spatial-resampling flag enables scaling; it is not a replacement chroma-siting
declaration. [ETSI Annex B](https://www.etsi.org/deliver/etsi_gs/CCM/001_099/001/01.01.01_60/gs_ccm001v010101p.pdf)
is an informative filter example, not permission to overwrite codec hints.
The initial declared VA scaling recipe therefore requires an actual top-left
EL frame at runtime. BL must report an explicitly supported left/top-left
location matched by the selected preparation policy. Unknown or contradictory
locations reject this route; AVFrame fields must not be relabelled to force it.
