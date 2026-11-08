/* Output colour mapping: Dolby Vision converted to an HDR10 (BT.2020 PQ)
 * picture by the engine instead of tunnelled to the TV
 * (docs/hdr10-output.md). The CPU half: yblod/dv_map.c turns a frame's RPU
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

enum {
    DVVK_MAP_TONE = 1u,        /* the tone curve is applied (else the plain decode) */
    DVVK_MAP_L1 = 2u,          /* the curve follows the frame's L1 (else static HDR10 metadata) */
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
    uint32_t lut_n;          /* the 3D LUT's points per axis */
    uint32_t list;           /* the cells buffer's fix-up list, word offset (the engine sets it; not in the key) */
    uint32_t pad;
    uint32_t black_in[4];    /* the stream's black (dvvk_plan.black: Y, Cb, Cr) ... */
    uint32_t black_out[4];   /* ... and its exact output codes (dvvk_map_set_black;
                              * the letterbox: no LUT or exact pass for it) */
    float tone_lut[DVVK_MAP_LUT];   /* PQ in (input min..max) -> PQ out */
} dvvk_map_gpu;

typedef struct {
    dvvk_map_gpu gpu;
    uint64_t key;              /* FNV-1a of gpu: the baked LUT is current when equal */
    dvvk_hdr_signal signal;    /* what the output is: for the HDMI HDR InfoFrame */
} dvvk_map;

/* 0: out set (mode DVVK_OUTPUT_HDR10*); -1 invalid input; -2 the metadata
 * can't be mapped (the frame is refused: an ordinary picture, as for a
 * stream the tunnel refuses). */
int dvvk_map_plan(const dvvk_output_mode *mode, const void *metadata, size_t metadata_size, dvvk_map *out);
/* The CPU reference of one sample: 12-bit codes in, Y'CbCr out (Y' 0..1,
 * Cb'/Cr' -0.5..0.5, BT.2020 non-constant luminance of the PQ R'G'B'),
 * double precision except the tone LUT (float, as the GPU's). Tests and
 * dvvk-hdr10-compare. */
void dvvk_map_sample(const dvvk_map_gpu *p, const double codes[3], double out[3]);
/* Its three steps, as the GPU splits them: the RPU's affine decode to the
 * source's nonlinear R'G'B' (L'M'S' for IPT, profile 5), clamped to 0..1
 * (the 3D LUT's domain; PQ's EOTF clamps there anyway); the 3D LUT's
 * function, nonlinear source to the output's PQ R'G'B'; Y'CbCr of that. */
void dvvk_map_nonlinear(const dvvk_map_gpu *p, const double codes[3], double nl[3]);
/* dvvk_map_rgb returns which way each clamp and branch went: where it differs
 * between neighbouring LUT points, the function has a kink between them and
 * the pack computes those pixels exactly instead of interpolating. */
uint32_t dvvk_map_rgb(const dvvk_map_gpu *p, const double nl[3], double rgb[3]);
void dvvk_map_ycc(const double rgb[3], double out[3]);
/* black_in = black (12-bit codes Y, Cb, Cr) and black_out its exact output
 * codes, quantised as the pack quantises. Not in dvvk_map.key (the bake
 * doesn't read them). */
void dvvk_map_set_black(dvvk_map_gpu *p, const uint32_t black[3]);

#if UINTPTR_MAX == UINT64_MAX
#ifdef __cplusplus
static_assert(sizeof(dvvk_map_gpu) == 1408, "dvvk_map_gpu layout");
#else
_Static_assert(sizeof(dvvk_map_gpu) == 1408, "dvvk_map_gpu layout");
_Static_assert(offsetof(dvvk_map_gpu, tone_lut) == 384, "dvvk_map_gpu layout");
#endif
#endif
