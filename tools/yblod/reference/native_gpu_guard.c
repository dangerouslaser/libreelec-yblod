#include "native_gpu_guard.h"
#include <stddef.h>

uint64_t yb_sizeof_gpu_width_report(void)
{
    return sizeof(struct yb_gpu_width_report);
}

static uint64_t magnitude(int64_t value)
{
    /* Metadata validation already excludes INT64_MIN; this identity also
     * avoids overflowing its negation if the helper's domain ever widens. */
    return value < 0 ? (uint64_t)(-(value + 1)) + UINT64_C(1) : (uint64_t)value;
}

static int add_magnitude(uint64_t *sum, int64_t value)
{
    const uint64_t term = magnitude(value);
    if (*sum > UINT64_MAX - term) return YB_INVALID_CONFIG;
    *sum += term;
    return YB_OK;
}

int yb_gpu_check_mapping_width(const struct yb_mapping_config *config,
                               struct yb_gpu_width_report *output)
{
    if (output == NULL) return YB_INVALID_ARGUMENT;
    int status = yb_validate_mapping(config);
    if (status != YB_OK) return status;
    struct yb_gpu_width_report report = {1, 0, 0, -1, -1};
    const uint64_t maximum_l1 = (uint64_t)INT64_MAX / (UINT64_C(1) << 20);
    for (int32_t component = 0; component < YB_COMPONENTS; ++component) {
        const struct yb_component_mapping *curve = &config->components[component];
        for (int32_t index = 0; index < curve->pivot_count - 1; ++index) {
            const struct yb_segment *segment = &curve->segments[index];
            if (segment->method != YB_MMR) continue;
            ++report.mmr_segment_count;
            uint64_t l1 = 0;
            status = add_magnitude(&l1, segment->constant);
            if (status != YB_OK) return status;
            for (int32_t row = 0; row < segment->order; ++row) {
                for (unsigned term = 0; term < YB_MMR_TERMS; ++term) {
                    status = add_magnitude(&l1, segment->coefficients[row][term]);
                    if (status != YB_OK) return status;
                }
            }
            if (l1 > report.worst_l1_bound) report.worst_l1_bound = l1;
            if (l1 > maximum_l1 && report.supported) {
                report.supported = 0;
                report.first_unsupported_component = component;
                report.first_unsupported_segment = index;
            }
        }
    }
    *output = report;
    return YB_OK;
}
