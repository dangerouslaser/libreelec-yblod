/* YBLOD: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10_expert.c) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Subset: cb1_display_primaries, unchanged (see cb1_hdr10_expert.h).
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Public player-led policy, not the proprietary Dolby content mapper. */
#include "cb1_hdr10_expert.h"

struct pl_raw_primaries cb1_display_primaries(const struct dvbridge_policy *policy)
{
    if(policy->lldv_edid_version){
        const double *xy=policy->lldv_primaries;
        return (struct pl_raw_primaries){.red={xy[0],xy[1]},.green={xy[2],xy[3]},
            .blue={xy[4],xy[5]},.white={.3127,.3290}};
    }
    return *pl_raw_primaries_get(policy->tv.gamut==DVBRIDGE_GAMUT_BT709?PL_COLOR_PRIM_BT_709:
        policy->tv.gamut==DVBRIDGE_GAMUT_P3_D65?PL_COLOR_PRIM_DISPLAY_P3:PL_COLOR_PRIM_BT_2020);
}
