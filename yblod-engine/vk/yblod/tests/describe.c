/* cb1_hdr10plus_describe on the statistics CB1's analysis test measures
 * (CB1/tests/hdr10plus_analysis.c at 9eb35aeb1146e9a6c3652b7a43225511887cdc17,
 * its non-GL part: YBLOD measures with the Vulkan pack, not CB1's GLES pass):
 * 2048 pixels, 512 each at 0, 160, 800 and 4000 nits.
 * SPDX-License-Identifier: MIT (as CB1's test) */
#include <assert.h>
#include <math.h>
#include <string.h>
#include "cb1_hdr10plus_analysis.h"

int yb_test_describe(void)
{
    struct cb1_hdr10plus_statistics out = {.maxscl = {160, 800, 4000}, .average_maxrgb = 1240, .count = 2048,
                                           .histogram = {[0] = 512, [10] = 512, [50] = 512, [250] = 512}};
    AVDynamicHDRPlus m = {0};
    uint8_t wire[31];
    assert(cb1_hdr10plus_describe(&m, &out, 992));
    assert(m.application_version == 1 && m.num_windows == 1 && m.params[0].tone_mapping_flag == 0);
    assert(m.params[0].distribution_maxrgb[1].percentile.num == 0);
    assert(m.params[0].distribution_maxrgb[2].percentile.num == 255);
    assert(cb1_hdr10plus_vsif(wire, &m, false, true) == CB1_HDR10PLUS_OK);
    assert(wire[7] == 126 && wire[8] == 78);
    assert(wire[9] == 0 && wire[12] == 0 && wire[13] == 10 && wire[14] == 50 && wire[17] == 250);
    struct cb1_hdr10plus_statistics impossible = out;
    impossible.average_maxrgb = 5000;
    AVDynamicHDRPlus saved = m;
    assert(!cb1_hdr10plus_describe(&m, &impossible, 992));
    assert(!memcmp(&m, &saved, sizeof(m)));
    assert(!cb1_hdr10plus_describe(&m, &out, 1000)); /* Curve target must match wire units. */
    out.histogram[0]++;
    assert(!cb1_hdr10plus_describe(&m, &out, 992));
    return 0;
}
