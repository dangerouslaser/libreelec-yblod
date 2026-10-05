/* Native-only library smoke test. No Python, video files, player or GPU. */
#include "native_composer.h"
#include "native_colour.h"
#include "native_y416.h"

int main(void)
{
    struct yb_mapping_config mapping = {0};
    mapping.bit_depth = 10;
    mapping.denominator = 23;
    for (unsigned channel = 0; channel < 3; ++channel) {
        struct yb_component_mapping *curve = &mapping.components[channel];
        curve->pivot_count = 2;
        curve->pivots[1] = 1023;
        curve->segments[0].method = YB_POLYNOMIAL;
        curve->segments[0].order = 1;
        curve->segments[0].coefficients[0][1] = INT64_C(1) << 23;
    }
    const struct yb_nlq_config correction = {10, 23, 512, 2048, 0, 1048576};
    const uint16_t y[] = {512}, zero[] = {0}, enhancement[] = {513};
    uint16_t mapped[1], output[1];
    int32_t residual[1], sum[1];
    if (yb_process_chunk(&mapping, &correction, 0, y, zero, zero,
                         enhancement, 1, 1, 12, mapped, residual, sum, output) != YB_OK ||
        mapped[0] != 32768 || residual[0] != 8 || sum[0] != 32776 || output[0] != 2049)
        return 1;

    struct yb_colour_parameters parameters = {0};
    parameters.code_scale = 4096;
    parameters.pq_policy = YB_PQ_REJECT_OUTSIDE_UNIT;
    for (unsigned channel = 0; channel < 3; ++channel) {
        const unsigned diagonal = 4 * channel;
        parameters.source_ycc[diagonal] = parameters.source_lms[diagonal] = 1;
        parameters.target_ycc[diagonal] = parameters.target_lms[diagonal] = 1;
    }
    struct yb_colour_config colour;
    struct yb_colour_result converted;
    const double codes[] = {2048, 1024, 3072};
    if (yb_colour_init(&parameters, &colour) != YB_COLOUR_OK ||
        yb_colour_process_chunk(&colour, codes, 1, 3, &converted, 1) != YB_COLOUR_OK ||
        converted.codes[0] != 2048 || converted.codes[1] != 1024 || converted.codes[2] != 3072)
        return 2;

    const uint8_t raw[] = {0x34, 0x12, 0xcd, 0xab, 0xff, 0xff, 0x01, 0x80};
    const yb_y416_surface surface = {raw, 8, 1, 1, 8, YB_Y416_LE_UYVA, 16, 10, 6};
    uint16_t u, luma, v, alpha;
    if (yb_y416_unpack_rows(&surface, 0, 1, &u, &luma, &v, &alpha, 1) != YB_Y416_OK ||
        u != 0x1234 || luma != 0xabcd || v != 0xffff || alpha != 0x8001)
        return 3;
    return 0;
}
