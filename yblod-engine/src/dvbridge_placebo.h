/* YBLOD: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/dvbridge_placebo.h) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Subset: struct dvbridge_color, struct dvbridge_hdr10_metadata and dvbridge_map_color, which the
 * Expert plan (cb1_hdr10_expert.c) calls, unchanged; the HDR10 session, the chroma map and
 * dvbridge_reference_map are not ported.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef DVBRIDGE_PLACEBO_H
#define DVBRIDGE_PLACEBO_H
#include <stdbool.h>
#include <stddef.h>
#include <libplacebo/colorspace.h>
#include "dvbridge_policy.h"

struct dvbridge_color {
    struct pl_color_space color;
    struct pl_color_repr repr;
    struct pl_dovi_metadata dovi;
};

struct dvbridge_hdr10_metadata {
    bool level6;
    unsigned max_luminance, min_luminance, max_cll, max_fall;
};
/* Output owns its mapping; do not copy it without rebinding repr.dovi. */
bool dvbridge_map_color(struct dvbridge_color *out, const void *metadata,
                       size_t bytes, bool enhancement_layer_paired);
#endif
