/*
 * This file is part of libplacebo.
 *
 * libplacebo is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * libplacebo is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with libplacebo. If not, see <http://www.gnu.org/licenses/>.
 */

/* YBLOD: the tone LUT of CroqueMr's CB1 Expert curve, from his libplacebo
 * patch CB1/patches/libplacebo/libplacebo-9918-expert-tone.patch (CB1 at
 * b5149a09d759ab2cc1dd8c0b6d156da67d70cae6), which bakes the signed curve
 * controls (slope, offset, power in -1..1, the L2 trims) into the LUT that
 * pl_shader_color_map_ex samples for an explicit cb1_tone_map: its
 * fill_tone_lut, unchanged but for the name (libplacebo's shader half is not
 * part of the engine; yblod/dv_map.c and shaders/common/dv_map.glsl sample
 * the LUT as that shader does). */
#include "cb1_expert_tone.h"

void pl_cb1_expert_tone_generate(float *data, const struct pl_tone_map_params *tone, const float shape[3])
{
    pl_tone_map_generate(data, tone);
    if (shape[0] == 0 && shape[1] == 0 && shape[2] == 0)
        return;
    float *values = data;
    const double low = tone->output_min, range = tone->output_max - low;
    for (size_t i = 0; i < tone->lut_size; i++) {
        const double x = (values[i] - low) / range, y = 1 - x;
        const double bend = shape[1]*y + shape[0]*x - 4*shape[2]*x*y;
        // Fixed endpoints/tangents. For all controls in [-1,1], derivative
        // >= 1 - 2/(3*sqrt(3)) - 6/16 > .24: no added plateau or reversal.
        values[i] = low + range * (x + x*x*y*y*bend);
    }
}
