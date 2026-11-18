/* YBLOD: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10_expert.h) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Subset: the Expert and player-led plans (cb1_hdr10_expert_prepare, cb1_player_led_prepare),
 * cb1_hdr10_expert_ceiling and cb1_display_primaries, unchanged; cb1_hdr10_expert_trim (a libplacebo
 * shader) is not ported: shaders/common/dv_map.glsl and yblod/dv_map.c carry its arithmetic.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef CB1_HDR10_EXPERT_H
#define CB1_HDR10_EXPERT_H
#include "dvbridge_creative.h"
#include "dvbridge_placebo.h"
#include <libplacebo/tone_mapping.h>

/* Frame-owned value plan. Source DOVI points into this owner, never a caller's
 * temporary metadata. Scalar scene data is not relabelled as CIE-Y metadata. */
struct cb1_hdr10_expert_plan {
    struct dvbridge_color source;
    struct pl_color_space target;
    struct dvbridge_hdr10_metadata signal;
    struct dvbridge_creative_plan creative;
    struct pl_tone_map_params tone;
    float tone_shape[3];
};
bool cb1_hdr10_expert_prepare(struct cb1_hdr10_expert_plan *out,
    const struct dvbridge_policy *policy,const void *metadata,size_t bytes,bool paired);
/* Offline display target uses the Expert policy's luminance and gamut fields. */
bool cb1_player_led_prepare(struct cb1_hdr10_expert_plan *out,
    struct dvbridge_cm4_coefficients *cm4,const struct dvbridge_policy *policy,
    const void *metadata,size_t bytes,bool paired);
/* Finite validated Expert policy only. Native output/range is not a user trim. */
float cb1_hdr10_expert_ceiling(const struct dvbridge_policy *policy);
struct pl_raw_primaries cb1_display_primaries(const struct dvbridge_policy *policy);
#endif
