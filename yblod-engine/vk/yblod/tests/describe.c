/* cb1_hdr10plus_describe on the statistics CB1's analysis test measures
 * (CB1/tests/hdr10plus_analysis.c at b5149a09d759ab2cc1dd8c0b6d156da67d70cae6,
 * its non-GL part: YBLOD measures with the Vulkan pack, not CB1's GLES pass):
 * 2048 pixels, 512 each at 0, 160, 800 and 4000 nits; and its luminance
 * patterns' scene, from the statistics that test asserts its pass measures.
 * SPDX-License-Identifier: MIT (as CB1's test) */
#include <assert.h>
#include <math.h>
#include <string.h>
#include "cb1_hdr10plus_analysis.h"

/* CB1's luminance_patterns(): 100x100 grey pixels, pattern 0 one at 800
 * nits, 4999 at 100.1 and 5000 at 99.9; pattern 1 two at 800, 4998 at 100.1;
 * pattern 2 all at 99.9 (100.1 and 99.9 nits are both bin 6). */
static struct cb1_hdr10plus_statistics pattern(unsigned n)
{
    unsigned bright = n == 2 ? 0 : n + 1;
    struct cb1_hdr10plus_statistics s = {.count = 10000, .luminance_valid = true};
    s.histogram[6] = 10000 - bright;
    s.histogram[50] = bright;
    for (unsigned c = 0; c < 3; c++)
        s.maxscl[c] = bright ? 800 : 99.9;
    s.average_maxrgb = n == 2 ? 99.9 : (bright * 800 + (5000 - bright) * 100.1 + 5000 * 99.9) / 10000;
    s.y99_nits = n == 1 ? 800 : 96;
    s.y100_percent = n == 2 ? 100 : 50;
    return s;
}

static void luminance_patterns(void)
{
    struct cb1_hdr10plus_analysis *ctx = cb1_hdr10plus_analysis_create_scene();
    assert(ctx);
    for (unsigned n = 0; n < 3; n++) {
        struct dvbridge_identity id = {100, n + 1, 1};
        cb1_hdr10plus_analysis_identify(ctx, id);
        struct cb1_hdr10plus_statistics stats = pattern(n);
        cb1_hdr10plus_analysis_stage_scene(ctx, &stats, false);
        AVDynamicHDRPlus metadata;
        uint8_t wire[31];
        assert(cb1_hdr10plus_describe(&metadata, &stats, 992));
        assert(cb1_hdr10plus_vsif(wire, &metadata, false, true) == CB1_HDR10PLUS_OK);
        assert(wire[10] == (n ? 50 : 6) && wire[11] == (n == 2 ? 67 : 50));
        cb1_hdr10plus_analysis_commit_scene(ctx);
        if (n == 2) {
            /* version 0's measurement: no luminance */
            stats = pattern(2);
            stats.luminance_valid = false;
            assert(cb1_hdr10plus_describe(&metadata, &stats, 992));
            assert(metadata.params[0].distribution_maxrgb[1].percentile.num == 0);
            assert(metadata.params[0].distribution_maxrgb[2].percentile.num == 255);
            id.picture++;
            cb1_hdr10plus_analysis_identify(ctx, id);
            stats = pattern(2);
            cb1_hdr10plus_analysis_stage_scene(ctx, &stats, true);
            assert(stats.y99_nits == 96 && stats.y100_percent == 100);
            /* A cancelled refresh must leave the last accepted picture's scene intact. */
            stats = pattern(2);
            cb1_hdr10plus_analysis_stage_scene(ctx, &stats, false);
            assert(stats.y99_nits == 800 && stats.y100_percent == 75);
            id.revision++;
            cb1_hdr10plus_analysis_identify(ctx, id);
            stats = pattern(2);
            cb1_hdr10plus_analysis_stage_scene(ctx, &stats, false);
            assert(stats.y99_nits == 96 && stats.y100_percent == 100);
        }
    }
    /* a cleared scene starts again with the next picture */
    cb1_hdr10plus_analysis_clear_scene(ctx);
    cb1_hdr10plus_analysis_identify(ctx, (struct dvbridge_identity){100, 4, 1});
    struct cb1_hdr10plus_statistics stats = pattern(0);
    cb1_hdr10plus_analysis_stage_scene(ctx, &stats, false);
    assert(stats.y99_nits == 96 && stats.y100_percent == 50);
    cb1_hdr10plus_analysis_destroy(&ctx);
    assert(!ctx);
}

int yb_test_describe(void)
{
    /* Green at 800 nits gives Y=542.4 (bin 34, 99.99th percentile 544),
     * brighter than the blue at 4000 nits; only black and red have Y <= 100 nits. */
    struct cb1_hdr10plus_statistics out = {.maxscl = {160, 800, 4000}, .average_maxrgb = 1240, .count = 2048,
                                           .histogram = {[0] = 512, [10] = 512, [50] = 512, [250] = 512},
                                           .y99_nits = 544, .y100_percent = 50, .luminance_valid = true};
    AVDynamicHDRPlus m = {0};
    uint8_t wire[31];
    assert(cb1_hdr10plus_describe(&m, &out, 992));
    assert(m.application_version == 1 && m.num_windows == 1 && m.params[0].tone_mapping_flag == 0);
    assert(cb1_hdr10plus_vsif(wire, &m, false, true) == CB1_HDR10PLUS_OK);
    assert(wire[7] == 126 && wire[8] == 78);
    assert(wire[10] == 34 && wire[11] == 50);
    assert(wire[9] == 0 && wire[12] == 0 && wire[13] == 10 && wire[14] == 50 && wire[17] == 250);
    struct cb1_hdr10plus_statistics impossible = out;
    impossible.average_maxrgb = 5000;
    AVDynamicHDRPlus saved = m;
    assert(!cb1_hdr10plus_describe(&m, &impossible, 992));
    assert(!memcmp(&m, &saved, sizeof(m)));
    assert(!cb1_hdr10plus_describe(&m, &out, 1000)); /* Curve target must match wire units. */
    /* luminance out of the fields' range */
    impossible = out;
    impossible.y99_nits = 4096;
    assert(!cb1_hdr10plus_describe(&m, &impossible, 992));
    impossible = out;
    impossible.y100_percent = 100.5;
    assert(!cb1_hdr10plus_describe(&m, &impossible, 992));
    out.histogram[0]++;
    assert(!cb1_hdr10plus_describe(&m, &out, 992));
    luminance_patterns();
    return 0;
}
