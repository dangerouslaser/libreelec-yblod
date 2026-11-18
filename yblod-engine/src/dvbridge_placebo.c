/* YBLOD: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/dvbridge_placebo.c) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Subset: dvbridge_map_color, unchanged (see dvbridge_placebo.h); include names changed
 * (dvbridge_metadata_bounds.h for dvbridge_metadata.h).
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Validate parsed Dolby Vision metadata before handing reshaping parameters to libplacebo. */
#include "dvbridge_placebo.h"
#include "dvbridge_metadata_bounds.h"
#include <libplacebo/utils/libav.h>
#include <math.h>

bool dvbridge_map_color(struct dvbridge_color *out, const void *metadata,
                       size_t bytes, bool enhancement_layer_paired)
{
    if (!out || !metadata || (uintptr_t)metadata % _Alignof(AVDOVIMetadata))
        return false;
    const AVDOVIMetadata *m = metadata;
    if (!dvbridge_metadata_bounds(m, bytes))
        return false;
    const AVDOVIRpuDataHeader *h = av_dovi_get_header(m);
    const AVDOVIDataMapping *map = av_dovi_get_mapping(m);
    const AVDOVIColorMetadata *color = av_dovi_get_color(m);
    if ((h->disable_residual_flag != 0 && h->disable_residual_flag != 1) ||
        color->signal_eotf != 65535 ||
        (color->signal_color_space != 0 && color->signal_color_space != 2) ||
        color->signal_eotf_param0 || color->signal_eotf_param1 || color->signal_eotf_param2 ||
        color->source_min_pq > color->source_max_pq || color->source_max_pq > 4095)
        return false;
    if (h->bl_bit_depth < 8 || h->bl_bit_depth > 16 || h->coef_log2_denom > 30)
        return false;
    if (!h->disable_residual_flag &&
        (h->el_bit_depth < 8 || h->el_bit_depth > 16 ||
         map->nlq_method_idc != AV_DOVI_NLQ_LINEAR_DZ))
        return false;
    for (int c = 0; c < 3; ++c) {
        const AVDOVIReshapingCurve *curve = &map->curves[c];
        if (curve->num_pivots < 2 || curve->num_pivots > 9)
            return false;
        if (!color->ycc_to_rgb_offset[c].den)
            return false;
        for (int p = 0; p < curve->num_pivots; ++p) {
            if (curve->pivots[p] >= (1u << h->bl_bit_depth) ||
                (p && curve->pivots[p] < curve->pivots[p - 1]))
                return false;
        }
        for (int p = 0; p + 1 < curve->num_pivots; ++p) {
            if (curve->mapping_idc[p] == AV_DOVI_MAPPING_POLYNOMIAL) {
                if (curve->poly_order[p] > 2)
                    return false;
            } else if (curve->mapping_idc[p] == AV_DOVI_MAPPING_MMR) {
                if (curve->mmr_order[p] < 1 || curve->mmr_order[p] > 3)
                    return false;
            } else {
                return false;
            }
        }
    }
    for (int i = 0; i < 9; ++i)
        if (!color->ycc_to_rgb_matrix[i].den || !color->rgb_to_lms_matrix[i].den)
            return false;
    struct dvbridge_color candidate = {0};
    pl_map_avdovi_metadata(&candidate.color, &candidate.repr, &candidate.dovi, m);
    if (candidate.dovi.nlq_active && !enhancement_layer_paired)
        return false;
    *out = candidate;
    out->repr.dovi = &out->dovi;
    return true;
}
