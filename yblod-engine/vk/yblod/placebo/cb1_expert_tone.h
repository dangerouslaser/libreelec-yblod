/* YBLOD: CroqueMr's CB1 Expert tone LUT (cb1_expert_tone.c, from his
 * libplacebo-9918-expert-tone.patch). SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <libplacebo/tone_mapping.h>

/* pl_tone_map_generate, then the signed curve controls (slope, offset,
 * power; 0 neutral) bent into the LUT between output_min and output_max, as
 * the patch's fill_tone_lut does for pl_color_map_args.cb1_tone_shape. */
void pl_cb1_expert_tone_generate(float *data, const struct pl_tone_map_params *tone, const float shape[3]);
