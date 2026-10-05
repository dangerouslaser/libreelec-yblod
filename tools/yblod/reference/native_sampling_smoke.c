/* Standalone CPU smoke test, not a pipeline/backend or rounding-policy choice.
 * Build (C11, no Python/EGL/GPU):
 * cc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow \
 *   native_sampling_smoke.c native_y416.c native_sampling_probe.c \
 *   native_annexb_probe.c -o native_sampling_smoke
 *
 * The explicit bilinear half-pixel and normalization divisor are diagnostic
 * inputs, NOT runtime texture-state assertions or informative Annex B weights.
 * Annex B uses a separate integer-coded fixture and independent hand literals.
 */
#include "native_y416.h"
#include "native_sampling_probe.h"
#include "native_annexb_probe.h"

#include <inttypes.h>
#include <stdio.h>

static int require(int condition, const char *name)
{
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", name);
        return 0;
    }
    return 1;
}

static void put_le16(uint8_t *destination, uint16_t word)
{
    destination[0] = (uint8_t)(word & UINT16_C(255));
    destination[1] = (uint8_t)(word >> 8);
}

static int same_words(const uint16_t *actual, const uint16_t *expected,
                      uint64_t count)
{
    uint64_t i;
    for (i = 0; i < count; ++i) {
        if (actual[i] != expected[i]) {
            return 0;
        }
    }
    return 1;
}

static int check_sampling(void)
{
    const uint16_t expected_y[3] = {32768, 32784, 65535};
    uint8_t packed[24];
    uint16_t u[3], y[3], v[3], alpha[3];
    yb_y416_surface surface = {
        packed, sizeof(packed), 3, 1, sizeof(packed),
        YB_Y416_LE_UYVA, 16, 10, 6
    };
    yb_sampling_plane plane = {y, 3, 3, 1, 3};
    /* Coordinates (x+1/2,y); raw/divisor explicitly declared as raw/65472. */
    yb_sampling_contract contract = {
        3, 1, 1, 0, 2, 2, 1, 2, 1, 10, 6, 65472
    };
    const yb_sampling_query queries[2] = {{0, 0}, {2, 0}};
    yb_sampling_result results[2];
    uint64_t i;

    for (i = 0; i < 3; ++i) {
        put_le16(packed + i * 8, (uint16_t)(100 + i));
        put_le16(packed + i * 8 + 2, expected_y[i]);
        put_le16(packed + i * 8 + 4, (uint16_t)(200 + i));
        put_le16(packed + i * 8 + 6, (uint16_t)(65535 - i));
    }
    if (!require(yb_y416_unpack_rows(&surface, 0, 1, u, y, v, alpha, 3)
                 == YB_Y416_OK, "lossless Y416 unpack") ||
        !require(same_words(y, expected_y, 3), "fractional/overshoot Y words")) {
        return 0;
    }
    for (i = 0; i < 3; ++i) {
        if (!require(u[i] == (uint16_t)(100 + i) &&
                     v[i] == (uint16_t)(200 + i) &&
                     alpha[i] == (uint16_t)(65535 - i),
                     "UYVA order and unchanged alpha")) {
            return 0;
        }
    }
    if (!require(yb_sampling_probe(&plane, &contract, queries, 2, results, 2)
                 == YB_SAMPLING_OK, "explicit half-pixel diagnostic")) {
        return 0;
    }
    if (!require(results[0].source_x_numerator == 1 &&
                 results[0].source_y_numerator == 0 &&
                 results[0].coordinate_denominator == 2,
                 "requested half-pixel coordinate") ||
        !require(results[0].raw_numerator == UINT64_C(32776) *
                 results[0].raw_denominator, "exact sampled raw word 32776") ||
        !require(results[0].native_denominator ==
                 UINT64_C(64) * results[0].raw_denominator,
                 "native Q6 preserves 512.125") ||
        !require(results[0].normalized_denominator ==
                 UINT64_C(65472) * results[0].raw_denominator,
                 "explicit diagnostic normalization") ||
        !require(results[1].raw_numerator == UINT64_C(65535) *
                 results[1].raw_denominator &&
                 results[1].raw_numerator > results[1].normalized_denominator,
                 "replicate edge preserves normalization overshoot")) {
        return 0;
    }
    return 1;
}

static int check_annexb(void)
{
    const uint16_t source[4] = {0, 1, 2, 8};
    const uint16_t vertical_y[8] = {0, 1, 0, 2, 2, 7, 2, 8};
    const uint16_t vertical_c[8] = {0, 1, 1, 3, 2, 6, 2, 8};
    const uint16_t final_y[16] = {
        0, 1, 1, 1, 0, 1, 2, 2, 2, 5, 7, 7, 2, 5, 8, 9
    };
    const uint16_t final_c[16] = {
        0, 1, 1, 1, 1, 2, 3, 3, 2, 4, 6, 6, 2, 5, 8, 9
    };
    const yb_annexb_plane plane = {source, 4, 2, 2, 2};
    const yb_annexb_rect vertical_rect = {0, 0, 2, 4};
    const yb_annexb_rect final_rect = {0, 0, 4, 4};
    const yb_annexb_rect tile_rect = {1, 1, 2, 2};
    uint16_t vertical[8], final[16], tile[4], scratch[2];
    const yb_annexb_output vertical_output = {vertical, 8, 2};
    const yb_annexb_output final_output = {final, 16, 4};
    const yb_annexb_output tile_output = {tile, 4, 2};
    uint32_t component;

    for (component = YB_ANNEXB_Y; component <= YB_ANNEXB_CR; ++component) {
        const uint16_t *expected_vertical = component == YB_ANNEXB_Y
            ? vertical_y : vertical_c;
        const uint16_t *expected_final = component == YB_ANNEXB_Y
            ? final_y : final_c;
        if (!require(yb_annexb_probe(&plane, component, YB_ANNEXB_VERTICAL_ONLY,
                     &vertical_rect, &vertical_output, 8, scratch, 2)
                     == YB_ANNEXB_OK, "Annex B vertical bounded call") ||
            !require(same_words(vertical, expected_vertical, 8),
                     "hand-derived Y/C vertical literals") ||
            !require(yb_annexb_probe(&plane, component, YB_ANNEXB_TWO_PASS,
                     &final_rect, &final_output, 16, scratch, 2)
                     == YB_ANNEXB_OK, "Annex B two-pass bounded call") ||
            !require(same_words(final, expected_final, 16),
                     "hand-derived Y/C final literals") ||
            !require(yb_annexb_probe(&plane, component, YB_ANNEXB_TWO_PASS,
                     &tile_rect, &tile_output, 4, scratch, 2)
                     == YB_ANNEXB_OK, "Annex B global partial rectangle") ||
            !require(tile[0] == expected_final[5] &&
                     tile[1] == expected_final[6] &&
                     tile[2] == expected_final[9] &&
                     tile[3] == expected_final[10], "tile is not a new edge")) {
            return 0;
        }
    }
    return 1;
}

int main(void)
{
    if (!check_sampling() || !check_annexb()) {
        return 1;
    }
    puts("{\"status\":\"complete\",\"cpu_only\":true,"
         "\"test_only\":true,\"pipeline_verified\":false,"
         "\"precision_policy_selected\":false,"
         "\"sampled_raw_word\":32776,\"normalization_divisor\":65472,"
         "\"overshoot_preserved\":true,\"annex_b_components_checked\":3}");
    return 0;
}
