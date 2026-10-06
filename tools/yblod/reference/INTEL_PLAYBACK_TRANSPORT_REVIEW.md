# Intel playback transport review

## What this review changes

The standalone integer reconstruction tests remain valuable accuracy gates,
but their CPU-packed sample uploads are not a decode-to-display playback path.
The recent lookup-table, reduced-readback and single-wait experiments did not
establish performance gains. This does not show that a GPU-resident playback
implementation would have the same speed.

This distinction applies to the new standalone engine tests, not the existing
Kodi Dolby path. A read-only source audit found that existing path already uses
VA-API decode, DMA-BUF/EGLImage textures and GPU composition. Its QSV scaler
also exports its output back to EGL. The task is to reuse/adapt that transport
for the new engine and verify precision, not to replace an assumed CPU-copy
production pipeline. A separate generic Kodi software-postprocessing route
contains CPU copies, but its existence does not show the native DV route uses it.

This is intended source behavior, not proof of the installed VM binary's live
route. At commit `3b0ce8ac4738b706b515dc0f9c2e4011aed31efa`, the audit checked:

- `projects/Generic/patches/kodi/kodi-9990-native-dv.patch`, SHA256
  `e702d2fd48a037ea70127251686936a3f4c0889fdbe977116b1158ec325aaab3`:
  native VA-API/texture acceptance and direct EL import.
- `projects/Generic/patches/kodi/kodi-9999-yblod-01-qsv-offload.patch`, SHA256
  `209e16d08cc04a15c34dbb182f8fde284004fc6aa0bc2ad58bd743caa6eb79ff`:
  explicit `VA_RT_FORMAT_YUV444_12` Y416 allocation, packed texture import,
  P010 source import and synchronous producer completion.

The existing QSV path explicitly declares twelve significant bits. That is
distinct from assuming sixteen-bit precision merely from its Y416 storage.

The next gate is a small standalone VA-API surface-export inventory, followed
by exact graphics import and surface-reuse tests. Keep the C reference and
existing Kodi playback unchanged. A repeated resident-input arithmetic test
can still isolate shader execution later, but must not be labelled playback.

## Primary-source findings

1. Intel supports video-memory surfaces through VA-API and VPL. A VPL API
   migration alone is not an established optimization. Our existing VA-API
   decode/scaling foundation can be retained.
   [Intel hardware guide](https://intel.github.io/libvpl/latest/programming_guide/VPL_prg_hw.html)

2. PRIME exports carry actual objects, plane/layer formats, object indices,
   offsets, pitches and modifiers. A VA FourCC alone is not enough to infer
   a packed linear memory layout.
   [libva descriptor](https://raw.githubusercontent.com/intel/libva/master/va/va_drmcommon.h)

3. Export does not synchronize. VA producer completion must precede external
   reads; external consumer work must finish before VA reuse. Owned exported
   descriptors must be closed.
   [libva export contract](https://raw.githubusercontent.com/intel/libva/master/va/va.h)

4. EGL modifier support can be external-texture-only. Successful image import
   is not proof of exact raw integer component access: external sampling may
   perform conversion. Query actual plane formats/modifiers and supported
   targets before choosing the shader representation.
   [EGL modifier specification](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_image_dma_buf_import_modifiers.txt)

5. Intel documents both fixed-function SFC and shader/kernel processing.
   Its feature table warns that SFC processing of 16-bit formats has 12-bit
   precision whereas kernel processing supports real 16-bit precision.
   A Y416 format label therefore does not prove scaling preserves all low bits.
   This review does not establish which engine any of our existing runs used.
   Validate synthetic low-bit ramps/impulses and record requested processing
   modes rather than assuming a hardware path.
   [Intel media features](https://github.com/intel/media-driver/blob/master/docs/media_features.md)

6. Queued frames can improve throughput, at a memory cost. Intel's VPL decoder
   guidance recommends different queue depths for memory and throughput.
   This is decoder guidance, not proof that our reconstruction needs four frames.
   Start with a bounded two-frame lifetime test after single-surface sharing
   is correct, accounting for both layers, references and output storage.
   [Intel decoding procedures](https://intel.github.io/libvpl/latest/programming_guide/VPL_prg_decoding.html)

7. Surface sharing does not add integer64 arithmetic to Kodi's GLES context.
   Our recorded capability probe found desktop GL integer64 available but not
   GLES. A desktop-GL or Vulkan reconstruction backend needs a safe output
   handoff to GLES. Vulkan shaderInt64 must be queried/enabled, not assumed.
   [Vulkan feature contract](https://docs.vulkan.org/refpages/latest/refpages/source/VkPhysicalDeviceFeatures.html)

## Current local evidence and limits

The existing scaler diagnostic uses vaPutImage to upload CPU pixels and
vaGetImage/vaMapBuffer to download scaled output; it does not test PRIME export
or graphics import. Its raw output is an accuracy fixture, not a zero-copy
playback measurement.

The VM remains on Intel Iris Xe/Tiger Lake. Its reported GPU clock limits
were 100–1300 MHz, with 400 MHz current clock and zero actual activity at the
idle observation. No clocks were changed. This idle snapshot does not explain
the clock behavior during earlier tests or prove that scheduling caused them.
No intel_gpu_top executable was found. Kodi remained active.

## Integer-shader compilation finding

The local Mesa 26.2.4 source makes another important distinction: advertised
integer64 shader support is not native efficient integer64 arithmetic.
Tiger Lake GT2 inherits the GFX12/GFX11 feature chain with `has_64bit_int=false`;
the Intel compiler consequently enables all integer64 lowering options.
Our exact-integer shader can therefore expand into smaller operations rather
than executing each 64-bit expression as one native operation. This is a
plausible instruction-count/register-pressure cost versus the older float
path, not measured attribution of our frame times.

Reviewed local source pins:

- `src/intel/dev/intel_device_info.c`, SHA256
  `de506e40168a09bcbd96a543e38f55b4ac48bc0695cef30e4c62b9a6e687d2aa`.
- `src/intel/compiler/brw/brw_compiler.c`, SHA256
  `787ef3a192776559defeb5e1fd37f402a57a3b610bf7501af05887a8bd44f4cf`.

[Mesa device source](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.4/src/intel/dev/intel_device_info.c),
[Mesa compiler source](https://gitlab.freedesktop.org/mesa/mesa/-/blob/mesa-26.2.4/src/intel/compiler/brw/brw_compiler.c).
Inspect actual compiled shader instructions, register use and spills before
optimizing arithmetic. Source feature flags alone do not establish those stats
for the running binary. Keep exactness and width/overflow gates if introducing
specialized narrower operations; never silently replace safe arithmetic.

## Incremental gates

- Inventory exported P010/Y416 surface layouts with complete producer
  synchronization, descriptor bounds checks and FD cleanup.
- Query matching EGL formats/modifiers/targets; reject unavailable exact access.
- Import a public synthetic surface and check every native word/component.
- Repeat producer/consumer handoff and reuse with finite waits and a bounded pool.
- Feed the unchanged reconstruction math from those surfaces; retain complete
  untimed stage comparison and report preparation/import/execution separately.
- Hand reconstructed output into Kodi and test actual high-bitrate playback.

No stage here authorizes changing rounding, chroma rules or colour limits to
match a licensed player's picture. No primary source establishes an Intel
fixed-function implementation of the full Dolby reconstruction.
