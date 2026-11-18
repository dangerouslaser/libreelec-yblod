/* big-fella's Dolby Vision source-tunnel engine on Vulkan compute
 * (docs/vulkan-engine.md).
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "dvvk_plan.h"   /* dvvk_plan_in */
#ifdef __cplusplus
extern "C" {
#endif

/* The library to dlopen (also its soname: build.rs reads it from here). A
 * layout change of any struct below is a new soname and DVVK_ABI_VERSION. */
#define DVVK_LIBRARY "libdv_engine_vk.so.1"
/* 1: libdv_engine_vk.so.0 (until 0.1.0-8); 2: dvvk_plan_in.cb1_contract;
 * 3 (YBLOD 0.4.0): dvvk_plan_in.el_scaler is DVVK_EL_ANNEXB (1) or
 * DVVK_EL_BILINEAR (2), nearest neighbour (0) is gone and refused. The
 * layouts are unchanged (the soname stays .so.1); a caller built for ABI 2
 * must not use this library, as its 0 would mean something else. */
#define DVVK_ABI_VERSION 3u
/* The ABI the loaded library was built with: a caller compares it with its
 * own DVVK_ABI_VERSION before using anything else. */
uint32_t dvvk_abi_version(void);

typedef struct dvvk_engine dvvk_engine;
typedef struct {
    dvvk_plan_in plan;            /* geometry, scaler, packet id, refresh, overlay */
    uint32_t bl_surface, el_surface;  /* VASurfaceID; el 0xffffffff = none */
    const void *metadata; size_t metadata_size;   /* ffmpeg-yblod AVDOVIMetadata */
    uint32_t output;              /* slot */
    uint32_t flags;               /* DVVK_FRAME_AUTO_OVERLAY: the overlay (and the
                                   * metadata's overlay edge) from the engine's
                                   * sources, set_subtitles / set_overlay */
    uint64_t release_wait;        /* explicit sync: write the output only once the
                                   * release timeline reaches this (0: no wait) */
} dvvk_frame;
#define DVVK_FRAME_AUTO_OVERLAY 1u
/* Desktop mode: the frame gets static graphics display management (L1 from
 * PQ(0.005) to the film's peak, a fixed average, no trims) instead of the
 * film's per-scene metadata: the film is a small part of a frame the desktop
 * fills (docs/research/media-following-colour.md). */
#define DVVK_FRAME_DESKTOP 2u

typedef struct {
    int32_t x, y;                 /* destination in the canvas */
    uint32_t w, h, dw, dh;        /* bitmap size; destination size (BGRA may scale) */
    uint32_t stride;
    uint32_t format;              /* 1 libass A8 with color, 2 BGRA premultiplied */
    uint32_t color;               /* libass 0xRRGGBBAA, AA = transparency */
    const void *data;
} dvvk_sub_part;

typedef struct {
    uint32_t width, height, format;   /* DRM fourcc: AR24, XR24, AB24, XB24 */
    uint64_t modifier;
    uint32_t num_planes;
    int fd[4];
    uint32_t offset[4], stride[4];
} dvvk_dmabuf;

/* Overlay sources for frames with DVVK_FRAME_AUTO_OVERLAY. */
int dvvk_set_subtitles(dvvk_engine *, const dvvk_sub_part *, uint32_t num);
int dvvk_set_overlay(dvvk_engine *, const dvvk_dmabuf *, uint64_t id);   /* NULL: none */
/* With flags: DVVK_OVERLAY_FLIP_Y, rows bottom first (a GL framebuffer's
 * texture: Kodi's GUI, read in place); its damage counts as everywhere. Other
 * flags: -1. */
#define DVVK_OVERLAY_FLIP_Y 1u
int dvvk_set_overlay_ex(dvvk_engine *, const dvvk_dmabuf *, uint64_t id, uint32_t flags);
/* Every frame that reads the overlay buffer leaves its fence on it as an
 * implicit read fence: a renderer that honours implicit sync may draw the
 * next contents into it at once (no copy, no CPU wait). */
/* The next dvvk_set_overlay's buffer differs from the previous one only in
 * these count rectangles (x, y, w, h each; 0: the same picture). Without it a
 * new buffer counts as changed everywhere. The engine then rewrites only what
 * changed in each output buffer (DVVK_DAMAGE=0: everything, every frame). */
int dvvk_set_overlay_damage(dvvk_engine *, const uint32_t *rects, uint32_t count);
/* 1 once a fence could not be attached as an implicit fence (older kernel):
 * wait for each ticket before committing or drawing into the overlay. */
int dvvk_implicit_failed(dvvk_engine *);
uint64_t dvvk_overlay_ticket(dvvk_engine *, uint64_t id);
int dvvk_create(int drm_fd, void *va_display, dvvk_engine **out);
/* dvvk_create with another canvas than 3840x2160 (an optional symbol, with
 * DVVK_OUTPUT_SDR; look it up with dlsym): the size of the output buffers
 * (dvvk_set_output), of the overlay (dvvk_set_overlay: a buffer of another
 * size is scaled; dvvk_set_overlay_rgba's picture; subtitle destinations)
 * and of dvvk_plan_in's destination rectangle, for a display mode of that
 * size. Width and height are multiples of 4, 64 to 4096; -2 otherwise.
 * Every output mode renders at any canvas; a picture larger than the canvas
 * is placed by its destination rectangle like any resized one (yblod's own
 * processing: CB1's contract is for unscaled pictures). Whether a display
 * takes the Dolby Vision tunnel at another size is the caller's business. */
int dvvk_create_canvas(int drm_fd, void *va_display, uint32_t width, uint32_t height, dvvk_engine **out);
/* dmabuf_fd: a linear XRGB8888 buffer of the canvas's size. */
int dvvk_set_output(dvvk_engine *, uint32_t slot, int dmabuf_fd, uint32_t stride);
/* 0: the picture is in the output; > 0 never; < 0: a dv_status (-2: not this
 * engine's frame, show an ordinary picture; -8: engine failure). */
int dvvk_render_sync(dvvk_engine *, const dvvk_frame *, uint32_t *error_flags);
/* Phase 1: the overlay picture for frames with plan.overlay set (RGBA8
 * premultiplied sRGB, the canvas's size, rows top first), copied in. Error flags
 * bit 8: an overlay colour the source can't represent. */
void dvvk_set_overlay_rgba(dvvk_engine *, const void *rgba, size_t stride);
/* Asynchronous: plan and submit without waiting; 0 and *ticket, or a
 * dv_status (*ticket is zero on failure). On success the output dmabuf carries the frame's fence as an
 * implicit write fence (commit it at once). The decoded surfaces must stay
 * alive until the ticket is done. A -8 recording/submission/export failure
 * requires destroying/recreating the engine; reset is not error recovery.
 * Export failure attempts a bounded drain, which can itself fail. On -8 keep
 * ALL inputs (including this frame with no returned ticket) until dvvk_drain
 * returns 1 and destruction succeeds. No device-loss drain is promised. */
int dvvk_submit(dvvk_engine *, const dvvk_frame *, uint64_t *ticket);
/* The CM4 / L2 result of the last frame planned (dvvk_plan_in.dm_options):
 * DVVK_CM4_STATUS_* | L2 blocks removed << 8, UINT32_MAX for NULL. Added in
 * 0.1.0-18 without an ABI change: callers look it up with dlsym. */
uint32_t dvvk_dm_status(dvvk_engine *);
/* Never blocks: *done when finished; *flags (1 range, 2 overflow, 0x100
 * overlay colour) once done. An error is not completion: do not read the
 * output or release its inputs on a failed poll. */
int dvvk_poll(dvvk_engine *, uint64_t ticket, int *done, uint32_t *flags);
/* 1 done, 0 timeout, < 0 failure. Only 1 authorizes reading the output or
 * releasing inputs. A failed reset retirement keeps imports and poisons submit. */
int dvvk_wait(dvvk_engine *, uint64_t ticket, uint64_t timeout_ns);
/* linux-drm-syncobj-v1: DRM syncobj fds of the frames' timeline (acquire
 * point = the frame's ticket) and of a release timeline for the compositor's
 * release points. The caller owns the fds. */
int dvvk_timelines(dvvk_engine *, int *acquire_syncobj_fd, int *release_syncobj_fd);
void dvvk_decode_waits(dvvk_engine *, uint64_t *fence, uint64_t *vasync);
/* 1 complete, 0 timeout, <0 failure; includes submitted work without a returned
 * ticket. Failure poisons submit. This retains all imports on every result. */
int dvvk_drain(dvvk_engine *, uint64_t timeout_ns);
/* 1 reset, 0 timeout, <0 failure. Failed reset retains imports. Poisoned
 * engines cannot reset successfully; destroy/recreate only after retirement. */
int dvvk_reset_checked(dvvk_engine *, uint64_t timeout_ns);
void dvvk_reset(dvvk_engine *);

/* Output mode (docs/hdr10-output.md). Optional symbols (dlsym), no ABI
 * change: an engine without them is the tunnel only.
 *   DVVK_OUTPUT_DV     the Dolby Vision tunnel (the default): the TV maps
 *   DVVK_OUTPUT_HDR10  HDR10: the engine converts to BT.2020 PQ as CroqueMr's
 *                      CB1 "Reference Basic" does (the film's own peak, L6 or
 *                      its mastering display, scene by scene from L1); the
 *                      picture is the same 12-bit 4:2:2 Y'CbCr byte layout as
 *                      the tunnel (limited range, no metadata in it), which
 *                      the display signals as YCbCr 4:2:2 12-bit BT.2020 with
 *                      dvvk_output_signal()'s HDR static metadata.
 * The mode applies from the next frame submitted; peak_nits/min_nits are
 * for target-display modes (reserved, 0). */
/*   DVVK_OUTPUT_HDR10PLUS (YBLOD 0.4.0) HDR10+: CroqueMr's CB1 Dolby Vision
 *                      -> HDR10+. The picture is the Master Reference
 *                      reconstruction in BT.2020 PQ WITHOUT tone mapping (the
 *                      receiver applies the HDR10+ curve once), in the same
 *                      byte layout as DVVK_OUTPUT_HDR10, with the same static
 *                      metadata (dvvk_output_signal, mode 2), plus per-frame
 *                      dynamic metadata from dvvk_hdr10plus_packet().
 * Statistics: the engine measures the active film area of every HDR10+
 * frame before the overlay (each channel's linear maximum, the average
 * maxRGB and a 256-bin maxRGB histogram, 16 nits a bin; for application
 * version 1 the BT.2020 luminance's 99.99th percentile and share at or below
 * 100 nits, over the scene as CB1 keeps it) in the pack (shaders/pack.comp
 * STATS), read back once the frame is done. */
/*   DVVK_OUTPUT_SDR  SDR (after YBLOD 0.5.0): the engine converts to the picture
 *                      of an SDR display (docs/intel-dv/OUTPUT-MODES.md): the
 *                      HDR10 recipe (libplacebo's spline tone curve on IPT's I,
 *                      scene by scene from L1) compressing to the display's
 *                      white, libplacebo's perceptual gamut mapping from the
 *                      source's primaries (L9) to BT.709, then the display's
 *                      inverse EOTF. The output is ordinary 8-bit R'G'B' in
 *                      XRGB8888 (no Dolby Vision or HDR signalling), dithered
 *                      with a fixed pattern, each pixel from its own luma and
 *                      chroma (the odd pixel's between its pair's sample and
 *                      the next pair's); an overlay is blended after the
 *                      conversion, as sRGB over the display's R'G'B', and has
 *                      to be the dvvk_set_overlay buffer alone, 8-bit, at the
 *                      canvas's size (a frame with subtitle bitmaps or
 *                      another overlay is refused, -2). Sources without
 *                      Dolby Vision play through the same conversion with
 *                      metadata made for them: HDR10+ (dvvk_hdr10plus_to_dovi),
 *                      HDR10 and HLG (dvvk_hdr10_to_dovi, DVVK_SDR_HLG).
 *                      peak_nits: the display's white in cd/m2 (0: 203;
 *                      40 to 1000, 20 to 1000 in a library with
 *                      dvvk_sdr_flags),
 *                      min_nits: its black (0: white / 1000, unless
 *                      DVVK_SDR_BLACK). flags
 *                      DVVK_SDR_*. An engine without it refuses the mode
 *                      (dvvk_set_output_mode returns -2); dvvk_output_modes
 *                      says so before an engine exists. */
enum { DVVK_OUTPUT_DV = 0, DVVK_OUTPUT_HDR10 = 1, DVVK_OUTPUT_HDR10PLUS = 2, DVVK_OUTPUT_SDR = 3, DVVK_OUTPUT_LLDV = 4 };
/* dvvk_output_mode.flags for DVVK_OUTPUT_SDR (0 for the other modes):
 * GAMMA22 a pure 2.2 power, black at the display's black (else BT.1886,
 * gamma 2.4 with the display's black); LIMITED codes 16..235 (else 0..255);
 * NO_DITHER the codes rounded; HLG the pictures are HLG (ARIB STD-B67, BT.2100)
 * instead of PQ: a plain HLG video with dvvk_hdr10_to_dovi's metadata, shown
 * as BT.2100's 1000 cd/m2 display would (system gamma 1.2) and converted
 * from there. */
enum { DVVK_SDR_GAMMA22 = 1u, DVVK_SDR_LIMITED = 2u, DVVK_SDR_NO_DITHER = 4u, DVVK_SDR_HLG = 8u };
/* CroqueMr's CB1 SDR targets (after YBLOD 0.5.1; dvvk_sdr_flags says whether
 * the library has them). A library without one refuses a mode that sets it
 * (-2), never approximates it.
 * POWER   a pure power of any exponent, black scaled as GAMMA22's (V =
 *         ((L - black) / (white - black))^(1 / gamma)): the gamma is
 *         reserved[DVVK_SDR_GAMMA_WORD] in thousandths, 1800 to 2800 (2400:
 *         libplacebo's GAMMA24, 2200: the same as GAMMA22). Not with GAMMA22.
 * BLACK   min_nits is the display's black as given, 0 included (true zero,
 *         libplacebo's PL_COLOR_HDR_BLACK as CB1 sets it), 0 to 5 cd/m2 and
 *         below the white. Without it 0 means white / 1000, and a black must
 *         be below white / 20.
 * BT2020  the display's primaries are BT.2020 (else BT.709): the gamut is
 *         mapped to them, dvvk_output_signal names them (signal the link
 *         as BT.2020 RGB, e.g. KMS Colorspace BT2020_RGB), and the overlay's
 *         sRGB colours are converted to them (its greys keep their codes).
 * Every reserved word a set flag does not give a meaning must be 0.
 * CB1's presets as dvvk_output_mode {mode, flags, peak_nits, min_nits, reserved}:
 *   Reference   {SDR, POWER | BLACK, 100, 0, {2400}}
 *   Bright room {SDR, POWER | BLACK, 200, 0, {2200}}
 *   Custom      {SDR, POWER | BLACK, peak 20..500, black 0..5, {gamma x 1000}}
 * each with BT2020 for CB1's BT.2020 gamut, LIMITED for limited range. */
enum { DVVK_SDR_POWER = 16u, DVVK_SDR_BLACK = 32u, DVVK_SDR_BT2020 = 64u };
#define DVVK_SDR_GAMMA_WORD 0
/* The DVVK_SDR_* flags this library takes (an optional symbol; no engine
 * needed): a library without it takes GAMMA22, LIMITED, NO_DITHER and HLG. */
uint32_t dvvk_sdr_flags(void);
/* Display-targeted outputs (after YBLOD 0.5.1): CroqueMr's CB1 "Expert"
 * recipe (CB1/src/cb1_hdr10_expert.c), the picture mapped by the engine to
 * a stated display (its peak, black and primaries) instead of to the film's
 * own peak: libplacebo's ST 2094-10 curve when the scene's L1 maximum is
 * above the display's peak, else a clip, over PQ(black)..PQ(peak), with the
 * L2 trims bent into it (or L8's CM4.0 controls, LLDV only), the gamut
 * mapped in the display's primaries, then sent as BT.2020 PQ in the same
 * 12-bit 4:2:2 Y'CbCr carrier as DVVK_OUTPUT_HDR10.
 *   DVVK_OUTPUT_HDR10 with DVVK_HDR10_TARGET: CB1's "HDR10 Rendering
 *     Reference" (LLDV Reference, HDR10 output). The flag on the HDR10 mode
 *     rather than a mode of its own: the output is HDR10 as before (the same
 *     carrier, the same signalling, the same overlay path), only the map's
 *     target differs. peak_nits 50 to 10000 cd/m2, min_nits 0 to 0.5 and
 *     below the peak (CB1's presets: OLED 0, LCD 0.005, projector 0.05),
 *     reserved[DVVK_TARGET_GAMUT_WORD] DVVK_GAMUT_* (0: P3-D65, CB1's
 *     default). dvvk_output_signal: the virtual target's static metadata
 *     (max and min luminance the display's, its gamut's primaries, MaxCLL
 *     and MaxFALL 0). Without the flag peak_nits and min_nits stay 0 and the
 *     bytes are those of plain DVVK_OUTPUT_HDR10.
 *   DVVK_OUTPUT_LLDV: player-led (low-latency) Dolby Vision, CB1's "LLDV
 *     Reference - Native": the display's own peak (peak_nits, 50 to 10000),
 *     black (min_nits: 0 to 1, 1.029 with a version 2 block, 0.5 without
 *     one; below the peak) and primaries (dvvk_set_display_primaries, else
 *     reserved[DVVK_TARGET_GAMUT_WORD]'s gamut, 0: BT.2020), from its Dolby
 *     Vision VSVDB (dvvk_lldv_display_from_vsvdb). The TV shows the picture
 *     without mapping it again: signal it with the Dolby VSIF's low-latency
 *     bit, the AVI InfoFrame's YCbCr 4:2:2 BT.2020 limited range, and NO HDR
 *     static metadata InfoFrame (this tree's kernel: DVBRIDGE_TUNNEL_FORMAT
 *     "lldv"). The carrier holds 12 useful bits, or 10 (DVVK_LLDV_10BIT: the
 *     codes' two low bits 0) where the display's 4:2:2 path takes 10. The
 *     overlay is blended after the map in the display's linear light, as
 *     CB1 does (sRGB through Kodi's transfer LUT, BT.709 to the display's
 *     primaries, white at 203 cd/m2), and has to be the dvvk_set_overlay
 *     buffer alone at the canvas's size, as for DVVK_OUTPUT_SDR. A frame
 *     with dvvk_plan_in.dm_options set is refused (-2): CB1's CM4.0 append
 *     and L2 removal for player-led output are not implemented.
 *     dvvk_output_signal: mode 4, eotf 2, the display's primaries and
 *     luminance, reserved[DVVK_SIGNAL_BITS_WORD] the useful bits; no
 *     InfoFrame to send from it.
 * dvvk_output_modes() has bit 1 << DVVK_OUTPUT_LLDV, and dvvk_target_flags()
 * DVVK_HDR10_TARGET, where the library has them; an older library refuses
 * them (-2). */
enum { DVVK_HDR10_TARGET = 1u };
enum { DVVK_LLDV_10BIT = 1u };
#define DVVK_TARGET_GAMUT_WORD 0
#define DVVK_SIGNAL_BITS_WORD 0
enum { DVVK_GAMUT_DEFAULT = 0, DVVK_GAMUT_BT709 = 1, DVVK_GAMUT_P3D65 = 2, DVVK_GAMUT_BT2020 = 3 };
/* An LLDV display's own primaries (an optional symbol): those its Dolby
 * Vision VSVDB codes, fitted inside BT.2020 as CB1 fits them
 * (dvvk_lldv_display_from_vsvdb's primaries), white D65. edid_version: the
 * block's version, 1 or 2; 0 (or NULL) clears them, and the mode's gamut is
 * used. Each primary's x and y above 0, x + y at most 1, the white inside
 * the triangle (CB1's dvbridge_policy_validate); -2 otherwise. Applies from
 * the next frame of DVVK_OUTPUT_LLDV; other modes don't read it. */
typedef struct {
    uint32_t edid_version;
    float xy[3][2];               /* R, G, B: CIE x, y */
    uint32_t reserved[3];
} dvvk_display_primaries;
typedef struct {
    uint32_t mode;
    uint32_t flags;               /* DVVK_SDR_* (SDR), else 0 */
    float peak_nits, min_nits;    /* 0: the stream's (SDR: the default display) */
    uint32_t reserved[4];
} dvvk_output_mode;
/* The output modes this library has, bit 1 << DVVK_OUTPUT_*. An optional
 * symbol (with DVVK_OUTPUT_SDR; no engine needed): a library without it has the
 * modes its other optional symbols say (never SDR). */
uint32_t dvvk_output_modes(void);
/* The last frame's output: what the HDR static metadata InfoFrame (CTA-861.3)
 * says. mode DVVK_OUTPUT_DV: everything 0. mode DVVK_OUTPUT_SDR: eotf 0, the
 * display's primaries (BT.709, or BT.2020 with DVVK_SDR_BT2020), white and
 * black, no InfoFrame to send. */
typedef struct {
    uint32_t mode;
    uint32_t eotf;                /* 2: SMPTE ST 2084 (PQ); 0: SDR */
    uint16_t primaries[3][2];     /* display primaries x, y (0.00002 units): R, G, B */
    uint16_t white[2];
    uint16_t max_luminance;       /* cd/m2 */
    uint16_t min_luminance;       /* 0.0001 cd/m2 */
    uint16_t max_cll, max_fall;   /* cd/m2; 0: unknown */
    uint32_t reserved[4];
} dvvk_hdr_signal;
int dvvk_set_output_mode(dvvk_engine *, const dvvk_output_mode *);
int dvvk_output_signal(dvvk_engine *, dvvk_hdr_signal *);

/* The upscaler (an optional symbol, no ABI change; look it up with dlsym:
 * an engine without it is bilinear): how a picture smaller than its
 * destination rectangle is enlarged, from the next frame submitted, in
 * every output mode. Only enlargements take it (neither side smaller, one
 * larger); a reduced or unscaled picture is unchanged, and so is an
 * enlarged one with DVVK_SCALER_BILINEAR (the default).
 *   DVVK_SCALER_BILINEAR   the pack's bilinear interpolation
 *   DVVK_SCALER_FSR1_EASU  AMD FidelityFX Super Resolution 1's EASU on the
 *                          reconstructed luma (the codes as a grey picture,
 *                          clamped at the picture's edges), chroma bilinear
 *   DVVK_SCALER_FSR1_RCAS  EASU, then FSR 1's RCAS sharpening (one stop,
 *                          noise limited) on that luma
 * FSR's pipelines and its luma plane (2 bytes a canvas pixel) are made on
 * the first enlarged picture that uses them (a short compile there unless
 * the pipeline cache has them). Returns 0, -2 for a method this library
 * doesn't have (the choice is unchanged), -1 for NULL. */
enum { DVVK_SCALER_BILINEAR = 0, DVVK_SCALER_FSR1_EASU = 1, DVVK_SCALER_FSR1_RCAS = 2 };
int dvvk_set_scaler(dvvk_engine *, uint32_t method);

/* HDR10+ dynamic metadata of an HDR10+ output frame (YBLOD 0.4.0; optional
 * symbol, look it up with dlsym). CB1's cb1_dv_hdr10plus_metadata (pinned
 * CB1 commit in yblod-engine/src/cb1_dv_hdr10plus.c): the statistics plus the
 * frame's L1 (with L3 folded once), and L2 or L8 where their luminous
 * response can be represented, fitted as ONE HDR10+ curve for a 992-nit
 * reference (the largest the HDMI field carries; not the TV's peak), the
 * quantized curve checked on grey and coloured probes (max normalized PQ
 * error 2/1023), else descriptive statistics only (no curve). No pixel is
 * changed by it.
 *   vsif   the complete 31-byte HDR10+ Vendor-Specific InfoFrame (CTA-861
 *          header 0x81 0x01 0x1b, checksum, the 27-byte payload: OUI
 *          0x90848B LSB first, application version in bits 7-6 of byte 7,
 *          ...), exactly what the kernel's HDR10PLUS_METADATA connector
 *          property takes as its blob (linux-9940 / YBLOD linux-9932):
 *          create a blob of these 31 bytes and set it in the same atomic
 *          commit as the frame's framebuffer.
 * Statistics: the ticket's own when that frame is done; otherwise the latest
 * finished HDR10+ frame's before it (one frame late at most in steady
 * playback, across a cut too), with statistics_ticket saying which. Never
 * blocks.
 * flags: DVVK_HDR10PLUS_V1 the sink's HDR10+ application version 1 (its
 * EDID VSVDB says so; else version 0), DVVK_HDR10PLUS_NO_DELAY the packet is
 * latched with its picture (the kernel's presentation contract). The
 * overlay flag (graphics_overlay_flag) is the ticket's: set when the frame
 * had an overlay.
 * Returns 0: *out filled, send vsif. 1: no finished frame's statistics yet
 * (the first frames after the mode is set): send no HDR10+ packet for this
 * frame. DVVK_HDR10PLUS_FALLBACK (-3): the metadata can't be represented
 * (out->reason, out->coverage say why): HDR10 only, clear the property.
 * -1: not a live HDR10+ frame's ticket (unknown, reused or a DV/HDR10
 * frame), or NULL arguments. */
enum { DVVK_HDR10PLUS_V1 = 1u, DVVK_HDR10PLUS_NO_DELAY = 2u };
#define DVVK_HDR10PLUS_FALLBACK (-3)
/* coverage: what the curve represents. 0 statistics only (no curve), 1 L1,
 * 2 L2 trims, 3 L8 (CM4) trims (CB1's enum cb1_dv_hdr10plus_coverage).
 * reason: 0 OK, 1 no usable L1 (statistics only), 2 trims not resolved,
 * 3 trims not representable (L1 curve sent instead), 4 the curve not
 * representable (statistics only) (enum cb1_dv_hdr10plus_reason). */
typedef struct {
    uint8_t vsif[31];
    uint8_t application_version;  /* 0 or 1, as in vsif */
    uint64_t statistics_ticket;   /* the frame whose statistics it carries */
    uint32_t coverage, reason;
    uint16_t effective_l1[3];     /* L1 min, max, avg (12-bit PQ) with L3 applied */
    uint16_t l3_used;
    double maximum_curve_pq_error, maximum_color_pq_error;
    /* the statistics sent: maxRGB average and channel maxima (cd/m2), pixels */
    double average_maxrgb, maxscl[3];
    uint64_t pixels;
    uint32_t reserved[4];
} dvvk_hdr10plus_metadata;
int dvvk_hdr10plus_packet(dvvk_engine *, uint64_t ticket, uint32_t flags, dvvk_hdr10plus_metadata *out);

/* HDR10+ -> Dolby Vision (YBLOD 0.4.0; optional symbol, no engine needed):
 * CroqueMr's CB1 cb1_hdr10plus_dovi_describe (pinned commit in
 * yblod-engine/src/cb1_hdr10plus_dovi.c) turned into the per-picture Dolby
 * Vision metadata an HDR10 base layer plays with as Profile 8.1 through the
 * tunnel: give it to dvvk_submit as dvvk_frame.metadata/metadata_size with
 * the decoded HDR10 picture as bl_surface, el_surface 0xffffffff, has_el 0.
 *   hdr10plus  the picture's AVDynamicHDRPlus (FFmpeg side data
 *              AV_FRAME_DATA_DYNAMIC_HDR_PLUS, as the FFmpeg the engine is
 *              built with lays it out), size its size. One window only.
 *              Its itu_t_t35_country_code 0 (stock FFmpeg leaves it so) is
 *              taken as 0xB5, the header FFmpeg checked; CB1's FFmpeg
 *              writes 0xB5 itself (since YBLOD 0.5.1).
 *   hdr10      the stream's static HDR10 metadata (NULL: unknown).
 *   previous   the previous picture's AVDynamicHDRPlus (NULL: none): a
 *              different scene (cb1_hdr10plus_dovi_same_scene) sets the
 *              scene refresh flag.
 *   out        an 8-aligned buffer of capacity bytes: an AVDOVIMetadata
 *              with its header, mapping, colour and extension blocks after
 *              it (av_dovi_metadata_alloc's layout, offsets from out).
 * The metadata: a Profile 8.1-style RPU (BL 10-bit, VDR 12-bit, no
 * residual) with an identity composer (each component one first-order
 * polynomial y = x over pivots 0..1023), BT.2020 PQ limited-range Y'CbCr to
 * RGB and RGB to LMS as Profile 8.1 streams carry them, the mastering
 * display's minimum and maximum as source_min_pq/source_max_pq (unknown:
 * 0.005 and 1000 cd/m2), and two extension blocks: L1 (min, max, avg: the
 * validated single-window MaxSCL as the peak, mean PQ from the percentiles'
 * weighted PQ trapezoids, else PQ(average maxRGB) as a labelled estimate;
 * min 0) and L6 (the static metadata: mastering max/min, MaxCLL, MaxFALL).
 * No L2/L8 trims are invented and HDR10+'s Bezier curve and saturation
 * weight are not translated (info says when the source had them); L3 is
 * neutral, i.e. absent (CM2.9): dvvk_plan_in.dm_options' CM4.0 modes can
 * still append the neutral CM4 blocks. The pixels are the decoded ones.
 * Returns 0 and *out_size; -1 invalid input (malformed HDR10+, NULL); -2 not
 * representable (several windows, no usable peak): play it as HDR10+/HDR10;
 * -3 capacity too small (*out_size: the size needed; DVVK_HDR10PLUS_DOVI_BYTES
 * always suffices). */
typedef struct {
    float max_luminance, min_luminance;   /* mastering display, cd/m2; 0: unknown */
    uint16_t max_cll, max_fall;           /* cd/m2; 0: unknown */
    uint32_t primaries;                   /* mastering display, DVVK_PRIMARIES_*; 0: unknown */
    uint32_t reserved;
} dvvk_hdr10_static;
/* dvvk_hdr10_static.primaries: written as an L9 block (source primaries),
 * which the SDR output's gamut mapping reads; unknown writes none. */
enum { DVVK_PRIMARIES_UNKNOWN = 0, DVVK_PRIMARIES_P3D65 = 1, DVVK_PRIMARIES_BT2020 = 2, DVVK_PRIMARIES_BT709 = 3 };
typedef struct {
    uint16_t l1_min, l1_max, l1_avg;      /* the L1 written (12-bit PQ) */
    uint16_t source_min_pq, source_max_pq;
    uint8_t source_fields, estimated_fields;   /* 1 min, 2 max, 4 avg: from HDR10+ / estimated */
    uint8_t untranslated_curve, untranslated_saturation, scene_refresh;
    uint8_t pad[3];
    uint32_t reserved[4];
} dvvk_hdr10plus_dovi_info;
#define DVVK_HDR10PLUS_DOVI_BYTES 8192u
int dvvk_hdr10plus_to_dovi(const void *hdr10plus, size_t size, const dvvk_hdr10_static *hdr10, const void *previous,
                           void *out, size_t capacity, size_t *out_size, dvvk_hdr10plus_dovi_info *info);
/* A plain HDR video (HDR10 or HLG: static metadata only) as metadata the
 * engine plays, for the SDR output (optional symbol, with DVVK_OUTPUT_SDR;
 * no engine needed): dvvk_hdr10plus_to_dovi's metadata without L1, so the
 * conversion's curve is the static one, from the mastering display's
 * maximum (libplacebo's HDR10 behaviour). An HLG video's is the same (its
 * Y'CbCr is BT.2020's too; hdr10 NULL): DVVK_SDR_HLG in the output mode says
 * what its codes mean. Unknown primaries are written as BT.2020, the
 * container's (L9). Every picture of the video takes the same bytes.
 * Returns as dvvk_hdr10plus_to_dovi (0, -1, -3). */
int dvvk_hdr10_to_dovi(const dvvk_hdr10_static *hdr10, void *out, size_t capacity, size_t *out_size);

/* Decoded surfaces are imported once and then known by their VASurfaceID
 * until a reset: reset whenever the decoder's surface pool changes (a new
 * AVHWFramesContext may reuse ids for other allocations), and keep the old
 * pool alive until then. */
/* Legacy void destruction waits for device idle. Idle failure terminates the
 * process without freeing resources; returning would imply unsafe completion.
 * Prefer a finite dvvk_drain before destruction. Vulkan device_wait_idle itself
 * has no timeout: no guarantee is made for a driver stuck inside that call. */
void dvvk_destroy(dvvk_engine *);
#if UINTPTR_MAX == UINT64_MAX
/* The layouts (LP64), as src/abi.rs asserts them for the Rust mirrors. */
DVVK_STATIC_ASSERT(sizeof(dvvk_frame) == 200, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, bl_surface) == 160, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, metadata) == 168, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, metadata_size) == 176, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, output) == 184, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, flags) == 188, "dvvk_frame layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_frame, release_wait) == 192, "dvvk_frame layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_sub_part) == 48, "dvvk_sub_part layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_sub_part, stride) == 24, "dvvk_sub_part layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_sub_part, color) == 32, "dvvk_sub_part layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_sub_part, data) == 40, "dvvk_sub_part layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_dmabuf) == 80, "dvvk_dmabuf layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_output_mode) == 32, "dvvk_output_mode layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_hdr_signal) == 48, "dvvk_hdr_signal layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_hdr_signal, max_luminance) == 24, "dvvk_hdr_signal layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_hdr10plus_metadata) == 128, "dvvk_hdr10plus_metadata layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_hdr10plus_metadata, statistics_ticket) == 32, "dvvk_hdr10plus_metadata layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_hdr10plus_metadata, average_maxrgb) == 72, "dvvk_hdr10plus_metadata layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_hdr10_static) == 20, "dvvk_hdr10_static layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_hdr10_static, primaries) == 12, "dvvk_hdr10_static layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_hdr10plus_dovi_info) == 36, "dvvk_hdr10plus_dovi_info layout");
DVVK_STATIC_ASSERT(sizeof(dvvk_display_primaries) == 40, "dvvk_display_primaries layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_dmabuf, modifier) == 16, "dvvk_dmabuf layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_dmabuf, num_planes) == 24, "dvvk_dmabuf layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_dmabuf, fd) == 28, "dvvk_dmabuf layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_dmabuf, offset) == 44, "dvvk_dmabuf layout");
DVVK_STATIC_ASSERT(offsetof(dvvk_dmabuf, stride) == 60, "dvvk_dmabuf layout");
#endif
#ifdef __cplusplus
}
#endif
