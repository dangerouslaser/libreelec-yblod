/* Output colour mapping: Dolby Vision converted to an HDR10 (BT.2020 PQ)
 * picture, or to an SDR (BT.709) one, by the engine instead of tunnelled to
 * the TV (docs/hdr10-output.md). The CPU half: yblod/dv_map.c turns a frame's RPU
 * and the output mode into the parameters of one per-pixel function of the
 * reconstructed 12-bit Y'CbCr, which shaders/map_bake.comp samples into a 3D
 * LUT (only when the parameters change) and the pack applies.
 *
 * The mapping is CroqueMr's CB1 "Dolby Vision to HDR10": Reference Basic
 * (CB1-DVHDR10B), whose libplacebo recipe (spline tone mapping, IPT, the
 * hull desaturation) is reproduced with libplacebo's own CPU code
 * (yblod/placebo, CB1's patched libplacebo e2972fdd), so the tone curve is
 * the same numbers. Not part of the public ABI: dv_engine_vk.h has the
 * caller's side (dvvk_output_mode, dvvk_hdr_signal). Rust mirrors it in
 * src/map.rs; the asserts below pin the layout. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "dv_engine_vk.h"

#define DVVK_MAP_LUT 256   /* tone LUT entries (CB1: lut_size 256) */
/* SDR output's 3D LUT lies over the reconstructed Y'CbCr codes (HDR10's over
 * the source's nonlinear R'G'B'), DVVK_MAP_SDR_NY x DVVK_MAP_SDR_NC^2 points:
 * luma from 0 to the scene's peak (dvvk_map_gpu.lut_box), chroma
 * DVVK_MAP_SDR_CHROMA codes either side of neutral (an HLG source:
 * DVVK_MAP_SDR_CHROMA_HLG). A display's R'G'B' near
 * zero is a small difference of the source's channels, and their noise in a
 * dark picture moves it by many 8-bit codes: over R'G'B' the LUT missed it by
 * more than the bake allows in a third of a dark frame's pixels (every pixel
 * of an IPT source, whose channels are L'M'S'). Along luma the channels move
 * together, and the chroma axes need only the colours pictures have. A
 * sample outside the box lands in a cell of its faces, which the bake marks
 * (computed exactly). */
#define DVVK_MAP_SDR_NY 129
#define DVVK_MAP_SDR_NC 65
#define DVVK_MAP_SDR_CHROMA 512.0f
#define DVVK_MAP_SDR_CHROMA_HLG 1024.0f
/* SDR output's tables (dvvk_map_tables; the GPU reads the same words): the
 * dither pattern, DVVK_MAP_DITHER^2 ranks 0 .. DVVK_MAP_DITHER^2 - 1, rows
 * first; then the gamut mapping LUT as libplacebo's shader holds it (an
 * RGBA16 UNORM texture of pl_gamut_map_generate, CB1: lut3d_size 48, 32,
 * 256), two words a node: I | P << 16, T, node (i, c, h) at
 * DVVK_MAP_GAMUT_AT + 2 * ((h * C + c) * I + i). */
#define DVVK_MAP_DITHER 64
#define DVVK_MAP_GAMUT_I 48
#define DVVK_MAP_GAMUT_C 32
#define DVVK_MAP_GAMUT_H 256
#define DVVK_MAP_GAMUT_AT (DVVK_MAP_DITHER * DVVK_MAP_DITHER)
#define DVVK_MAP_TABLE_WORDS (DVVK_MAP_GAMUT_AT + 2 * DVVK_MAP_GAMUT_I * DVVK_MAP_GAMUT_C * DVVK_MAP_GAMUT_H)

enum {
    DVVK_MAP_TONE = 1u,        /* the tone curve is applied (else the plain decode) */
    DVVK_MAP_L1 = 2u,          /* the curve follows the frame's L1 (else static HDR10 metadata) */
    DVVK_MAP_SDR = 4u,         /* the output is the display's R'G'B' (else BT.2020 PQ Y'CbCr) */
    DVVK_MAP_GAMUT = 8u,       /* SDR: the gamut mapping LUT is applied */
    DVVK_MAP_DITHER_ON = 16u,  /* SDR: the codes are dithered (else rounded) */
    DVVK_MAP_HLG = 32u,        /* SDR: the source's R'G'B' is HLG (else PQ): src_trc, src_luma */
    DVVK_MAP_BT2020 = 64u,     /* SDR: the display is BT.2020 (lms2rgb): the overlay's
                                * BT.709 converted (dvvk_map_layer_bt2020) */
    DVVK_MAP_GAMUT_EXACT = 128u, /* SDR: the gamut LUT read with exact weights, not the sampler's
                                  * (CB1's targets, DVVK_SDR_POWER, _BLACK, _BT2020, above a zero black) */
    DVVK_MAP_EXPERT = 256u,    /* CB1's Expert recipe for a stated display (dvvk_map_gpu's ex_*):
                                * DVVK_OUTPUT_HDR10 with DVVK_HDR10_TARGET, or with ... */
    DVVK_MAP_LLDV = 512u,      /* ... DVVK_OUTPUT_LLDV: the LLDV pack (and the overlay after the map) */
};

/* Expert (DVVK_MAP_EXPERT): CroqueMr's CB1/src/cb1_hdr10_expert.c prepare()
 * and the shaders his renderer runs with it (dvbridge_render.c
 * player_led_map, reference_output, dvbridge_pack_player_led_422; libplacebo
 * pl_shader_color_map_ex with his 9918 explicit tone curve), as one function
 * of the reconstructed codes. Linear light is libplacebo's, 1 = 203 cd/m2.
 * ex_flags: */
#define DVVK_MAP_EXPERT_LUT 4096   /* the tone LUT's entries at most (CB1: 1024 compressing, 4096 clipping) */
enum {
    DVVK_EX_TONE = 1u,         /* the tone curve on IPT's I (and the hull desaturation) */
    DVVK_EX_FAST = 2u,         /* no curve and no gamut map: the matrix ex_fast (libplacebo's fast path) */
    DVVK_EX_EDID = 4u,         /* the display's own primaries: ex_basis after the map */
    DVVK_EX_CM4 = 8u,          /* L8's CM4.0 controls (dvbridge_creative_cm4_shader), ex_cm4_* */
    DVVK_EX_CM4_TRIM = 16u,    /* ... in the CM4 target's primaries (EDID: ex_to_trim, ex_from_trim) */
    DVVK_EX_CHROMA = 32u,      /* cb1_hdr10_expert_trim's chroma and saturation (ex_chroma) */
    DVVK_EX_KEEP_BLACK = 64u,  /* signal black (all channels' light 0) stays exact zero (black 0) */
    DVVK_EX_LIFT_BLACK = 128u, /* ... and a positive CM4 offset lifts it (player_led_map's lift_black) */
    DVVK_EX_GUI_BT709 = 256u,  /* LLDV: the overlay's BT.709 is converted (ex_gui), else the display is BT.709 */
};

/* The GPU's parameters (std430: vec3s padded to vec4; matrices row-major,
 * three padded rows each). Everything the bake reads is in here, so equal
 * bytes = an equal LUT (dvvk_map.key hashes them). */
typedef struct {
    float ycc[12];           /* rows of ycc_to_rgb (code/4095 in), w: unused */
    float ycc_offset[4];     /* added after the matrix */
    float src_lms2rgb[12];   /* Dolby's HPE LMS -> BT.2020 times rgb_to_lms */
    float rgb2lms[12];       /* BT.2020 RGB -> IPT's LMS (libplacebo pl_ipt_rgb2lms) */
    float lms2rgb[12];       /* the output's LMS -> RGB (pl_ipt_lms2rgb) */
    float lms2ipt[12];       /* pl_ipt_lms2ipt */
    float ipt2lms[12];       /* pl_ipt_ipt2lms */
    float tone_in[4];        /* x: input min, y: input max (PQ), z: 1/(max-min) */
    float tone_out[4];       /* x: output min, y: output max (PQ) */
    uint32_t flags;          /* DVVK_MAP_* */
    uint32_t lut_n;          /* the 3D LUT's points per axis (SDR: per chroma axis) */
    uint32_t list;           /* the cells buffer's fix-up list, word offset (the engine sets it; not in the key) */
    uint32_t lut_ny;         /* SDR: the 3D LUT's points along the luma axis (0 otherwise) */
    uint32_t black_in[4];    /* the stream's black (dvvk_plan.black: Y, Cb, Cr) ... */
    uint32_t black_out[4];   /* ... and its exact output codes (dvvk_map_set_black;
                              * the letterbox: no LUT or exact pass for it; LLDV:
                              * unrounded, float bits) */
    float tone_lut[DVVK_MAP_LUT];   /* PQ in (input min..max) -> PQ out */
    /* SDR output (all 0 otherwise) */
    float gamut_at[4];       /* the gamut LUT's I coordinate: x * I + y */
    float out_trc[4];        /* the display's inverse EOTF of light L (1 = 10000 cd/m2):
                              * V = pow(max(x * L + y, 0), z) - w */
    float out_code[4];       /* the output codes: x * clamp(V, 0, 1) + y */
    uint32_t gamut_key[2];   /* names the gamut LUT's contents (dvvk_map.gamut_key) */
    float lut_box[2];        /* the 3D LUT's domain, in the reconstructed codes: luma 0 .. [0],
                              * each chroma 2048 - [1] .. 2048 + [1] (below) */
    /* an HLG source (DVVK_MAP_HLG; all 0 otherwise): libplacebo's
     * pl_shader_linearize, the inverse OETF of x: (1 - b) V + b, then the OOTF:
     * light (1 = 10000 cd/m2) = z * E * pow(src_luma . E, y), E the scene's
     * light over 12 */
    float src_trc[4];        /* x: b (the black lift), y: the system gamma - 1, z: the peak */
    float src_luma[4];       /* the source primaries' luminance coefficients */
    /* Expert (DVVK_MAP_EXPERT; all 0 otherwise). tone_in is the curve's
     * domain, lms2rgb the basis's (libplacebo's dst.primaries), rgb2lms
     * BT.2020's; matrices are rows (three padded rows each) but the CM4
     * ones, which are CB1's GLSL columns. */
    uint32_t ex_flags;       /* DVVK_EX_* */
    uint32_t ex_lut_n;       /* the tone LUT's entries (ex_tone_lut) */
    uint32_t ex_bits;        /* LLDV: the carrier's useful bits (12, or 10) */
    uint32_t ex_pad;
    float ex_fast[12];       /* BT.2020 -> the basis (libplacebo's fast path), or the identity */
    float ex_basis[12];      /* EDID: the basis -> the display's primaries (relative colorimetric) */
    float ex_to_trim[12];    /* EDID + CM4: the display -> the CM4 target's primaries */
    float ex_from_trim[12];  /* ... and back */
    float ex_cm4_sop[4];     /* slope, offset, power, peak (cd/m2) */
    float ex_cm4_shape[4];   /* mid exponent, clip strength, log2 chroma base, log2 saturation */
    float ex_cm4_flags[4];   /* SOP, mid contrast, clip, colour active (1 or 0) */
    float ex_cm4_luma[4];
    float ex_cm4_rgb_lms[12], ex_cm4_lms_rgb[12], ex_cm4_residual[12];   /* columns */
    float ex_cm4_centres[8], ex_cm4_gains[8], ex_cm4_turns[8];          /* six each */
    float ex_chroma[4];      /* expert_chroma x, y; z: expert_cap (the peak / 203, rounded down) */
    float ex_luma[4];        /* expert_luma: the display's (its primaries') luminance row */
    float ex_out[12];        /* the display's RGB -> BT.2020: LLDV the pack's lldv_matrix (relative
                              * colorimetric, or the identity), HDR10 xyz2rgb(BT.2020) * rgb2xyz */
    float ex_scale[4];       /* LLDV: x 203 / peak (into the carrier's 0..1), y peak / 203 (out of it);
                              * HDR10: z the PQ ceiling (cb1_hdr10_expert_ceiling) */
    float ex_gui[12];        /* LLDV: BT.709 -> the display's primaries (the overlay), relative colorimetric */
    float ex_out_inv[12];    /* LLDV: ex_out's inverse (the pack takes a sample under the overlay back
                              * to the display's light; the display's gamut lies inside BT.2020) */
    float ex_tone_lut[DVVK_MAP_EXPERT_LUT];   /* PQ in (tone_in) -> PQ out, ex_lut_n of them */
} dvvk_map_gpu;

typedef struct {
    dvvk_map_gpu gpu;
    uint64_t key;              /* FNV-1a of gpu: the baked LUT is current when equal */
    dvvk_hdr_signal signal;    /* what the output is: for the HDMI HDR InfoFrame */
    /* SDR output: what the gamut LUT is made from (dvvk_map_tables): the
     * source's and the display's primaries (R, G, B, white: x, y) and the
     * display's black and white (PQ). gamut_key names them: tables made for
     * an equal key are current. */
    float gamut_prim[2][8];
    float gamut_luma[2];
    uint64_t gamut_key;
} dvvk_map;

/* 0: out set (mode DVVK_OUTPUT_HDR10*, DVVK_OUTPUT_SDR); -1 invalid input;
 * -2 the metadata can't be mapped (the frame is refused: an ordinary
 * picture, as for a stream the tunnel refuses). */
int dvvk_map_plan(const dvvk_output_mode *mode, const void *metadata, size_t metadata_size, dvvk_map *out);
/* The same with an LLDV display's own primaries (NULL or version 0: none). */
int dvvk_map_plan_display(const dvvk_output_mode *mode, const dvvk_display_primaries *display, const void *metadata,
                          size_t metadata_size, dvvk_map *out);
/* Whether a display-targeted mode (HDR10 with DVVK_HDR10_TARGET, LLDV) and
 * its primaries are a display CB1's policy takes (dvbridge_policy_validate):
 * 1 yes, 0 no; -1 not such a mode. */
int dvvk_map_target_valid(const dvvk_output_mode *mode, const dvvk_display_primaries *display);
/* Expert: the display's linear light (1 = 203 cd/m2, its primaries) of a
 * nonlinear source sample before the output's tail (LLDV: divided by the
 * peak, 0..1, what CB1's player-led texture holds before the GUI). */
void dvvk_map_expert_display(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double v[3]);
/* LLDV: CB1's player_led_gui on v (dvvk_map_expert_display's), a pixel of
 * the overlay (8-bit R, G, B, A as the shell holds it) blended in the
 * display's linear light; degamma: the engine's 256 sRGB entries as the
 * shader samples them (dvvk_map_lldv_degamma). */
void dvvk_map_lldv_gui(const dvvk_map_gpu *p, const uint8_t rgba[4], double v[3]);
double dvvk_map_lldv_degamma(double code);
/* LLDV: v to the carrier's BT.2020 PQ R'G'B' (dvbridge_pack_player_led_422's
 * lldv_matrix, clamp, scale, PQ). */
void dvvk_map_lldv_encode(const dvvk_map_gpu *p, const double v[3], double pq[3]);
/* SDR output's tables for `map` (DVVK_MAP_TABLE_WORDS words): the dither
 * pattern and the gamut LUT (pl_gamut_map_generate: tens of milliseconds, so
 * only when map->gamut_key changes; a map without DVVK_MAP_GAMUT leaves the
 * LUT's words alone). */
void dvvk_map_tables(const dvvk_map *map, uint32_t *tables);
/* The CPU reference of one sample: 12-bit codes in; out Y'CbCr (Y' 0..1,
 * Cb'/Cr' -0.5..0.5, BT.2020 non-constant luminance of the PQ R'G'B'), or
 * with DVVK_MAP_SDR the display's R'G'B' (0..1). Double precision except
 * the tone LUT (float, as the GPU's) and the gamut LUT (16 bits, as the
 * GPU's). `tables`: dvvk_map_tables' (read with DVVK_MAP_GAMUT only). Tests,
 * dvvk-hdr10-compare and dvvk-sdr-compare. */
void dvvk_map_sample(const dvvk_map_gpu *p, const uint32_t *tables, const double codes[3], double out[3]);
/* Its three steps, as the GPU splits them: the RPU's affine decode to the
 * source's nonlinear R'G'B' (L'M'S' for IPT, profile 5; HLG's R'G'B' with
 * DVVK_MAP_HLG), clamped to 0..1
 * (HDR10's 3D LUT's domain; SDR output: 0..1.5 for a PQ source, and an HLG
 * one at 0 only: its signal goes on above nominal white); the 3D LUT's
 * function, nonlinear source to the output's R'G'B' (PQ, or the display's,
 * clamped to 0..1); Y'CbCr of that (not for SDR). */
void dvvk_map_nonlinear(const dvvk_map_gpu *p, const double codes[3], double nl[3]);
/* dvvk_map_rgb returns which way each clamp and branch went: where it differs
 * between neighbouring LUT points, the function has a kink between them and
 * the pack computes those pixels exactly instead of interpolating. */
uint32_t dvvk_map_rgb(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double rgb[3]);
void dvvk_map_ycc(const double rgb[3], double out[3]);
/* SDR: the code of an R'G'B' value (dvvk_map_rgb's) at pixel (x, y), as the
 * pack quantises it: dithered with the tables' pattern, or rounded. */
uint32_t dvvk_map_sdr_code(const dvvk_map_gpu *p, const uint32_t *tables, double v, uint32_t x, uint32_t y);
/* SDR with DVVK_MAP_BT2020: an overlay colour (R'G'B' 0..1, not
 * premultiplied: the BT.709 display's codes) as the BT.2020 display's codes
 * of the same light, through the display's transfer (out_trc), as the pack
 * converts the shell's layer. */
void dvvk_map_layer_bt2020(const dvvk_map_gpu *p, double v[3]);
/* black_in = black (12-bit codes Y, Cb, Cr) and black_out its exact output
 * codes, quantised as the pack quantises (SDR: undithered R, G, B). Not in
 * dvvk_map.key (the bake doesn't read them). */
void dvvk_map_set_black(dvvk_map_gpu *p, const uint32_t *tables, const uint32_t black[3]);

#if UINTPTR_MAX == UINT64_MAX
#ifdef __cplusplus
static_assert(sizeof(dvvk_map_gpu) == 18592, "dvvk_map_gpu layout");
#else
_Static_assert(sizeof(dvvk_map_gpu) == 18592, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, tone_lut) == 384, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, gamut_at) == 1408, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, src_trc) == 1472, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, ex_flags) == 1504, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, ex_cm4_sop) == 1712, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, ex_chroma) == 2016, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, ex_tone_lut) == 2208, "dvvk_map_gpu layout");
_Static_assert(sizeof(dvvk_map) == 18728, "dvvk_map layout");
_Static_assert(offsetof(dvvk_map, gamut_prim) == 18648, "dvvk_map layout");
#endif
#endif
