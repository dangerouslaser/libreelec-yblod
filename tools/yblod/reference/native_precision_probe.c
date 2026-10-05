#include "native_precision_probe.h"
#include <stddef.h>

static int check(const struct yb_nlq_config *config, int64_t word)
{
    int status = yb_validate_nlq(config);
    if (status != YB_OK) return status;
    if (config->bit_depth != 10) return YB_INVALID_CONFIG;
    if (word < 0 || word > 65472) return YB_INVALID_SAMPLE;
    return YB_OK;
}

int yb_probe_quantized(const struct yb_nlq_config *config, int64_t word,
                       int32_t policy, int32_t *sample, int64_t *residual)
{
    int status;
    int64_t native, answer, remainder;
    if (sample == NULL || residual == NULL) return YB_INVALID_ARGUMENT;
    if (policy < YB_PROBE_FLOOR || policy > YB_PROBE_TIES_EVEN)
        return YB_INVALID_ARGUMENT;
    status = check(config, word);
    if (status != YB_OK) return status;
    native = word / 64;
    remainder = word % 64;
    if (policy == YB_PROBE_HALF_UP && remainder >= 32) ++native;
    if (policy == YB_PROBE_TIES_EVEN &&
        (remainder > 32 || (remainder == 32 && native % 2 != 0))) ++native;
    status = yb_nlq(config, native, &answer);
    if (status != YB_OK) return status;
    *sample = (int32_t)native;
    *residual = answer;
    return YB_OK;
}

int yb_probe_literal(const struct yb_nlq_config *config, int64_t word,
                     struct yb_probe_rational *result)
{
    int status;
    int64_t delta, sign, numerator, limit, capped, divisor;
    struct yb_probe_rational local;
    if (result == NULL) return YB_INVALID_ARGUMENT;
    status = check(config, word);
    if (status != YB_OK) return status;
    delta = word - (int64_t)config->offset * 64;
    sign = (delta > 0) - (delta < 0);
    /* Accepted depth10/D<=32 bounds: |2*delta-64*sign|<=130944,
     * coefficients<2^33. Products/sums are <2^51, within signed64. */
    numerator = (2 * delta - 64 * sign) * (int64_t)config->slope
                + 128 * sign * (int64_t)config->threshold;
    limit = 128 * (int64_t)config->maximum;
    capped = numerator < -limit ? -limit : numerator > limit ? limit : numerator;
    divisor = INT64_C(64) * (INT64_C(1) << (config->denominator - 15));
    local.uncapped_numerator = numerator;
    local.capped_numerator = capped;
    local.divisor = (uint64_t)divisor;
    local.floored_residual = capped / divisor - (capped % divisor < 0);
    *result = local;
    return YB_OK;
}
