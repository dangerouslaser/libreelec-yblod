/* YBLOD: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10_expert.h) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Subset: cb1_display_primaries, which dvbridge_creative's resolver calls; the HDR10 Expert and
 * player-led renderers (libplacebo shaders) are not ported.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef CB1_HDR10_EXPERT_H
#define CB1_HDR10_EXPERT_H
#include "dvbridge_creative.h"

struct pl_raw_primaries cb1_display_primaries(const struct dvbridge_policy *policy);
#endif
