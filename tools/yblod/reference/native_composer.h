#ifndef YBLOD_NATIVE_COMPOSER_H
#define YBLOD_NATIVE_COMPOSER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Fixed-size, caller-owned integer metadata. Unused fields must be zero.
 * No buffer ownership, fractional transport or complete RPU parsing is implied.
 */
#define YB_MAX_PIVOTS 17
#define YB_MAX_SEGMENTS 16
#define YB_COMPONENTS 3
#define YB_MMR_TERMS 7

enum yb_status {
    YB_OK = 0,
    YB_INVALID_ARGUMENT = 1,
    YB_INVALID_CONFIG = 2,
    YB_INVALID_SAMPLE = 3
};

enum yb_method { YB_POLYNOMIAL = 0, YB_MMR = 1 };

struct yb_segment {
    int32_t method;
    /* Polynomial degree 1..2; MMR order 1..3. */
    int32_t order;
    int64_t constant;
    /* Polynomial coefficients occupy coefficients[0][0..order]. */
    int64_t coefficients[3][YB_MMR_TERMS];
};

struct yb_component_mapping {
    int32_t pivot_count;
    int32_t pivots[YB_MAX_PIVOTS];
    struct yb_segment segments[YB_MAX_SEGMENTS];
};

struct yb_mapping_config {
    int32_t bit_depth;
    /* Mapper-only denominator 13..32. A frame adapter also checks EL depth. */
    int32_t denominator;
    struct yb_component_mapping components[YB_COMPONENTS];
};

struct yb_nlq_config {
    int32_t bit_depth;
    int32_t denominator;
    int32_t offset;
    uint64_t slope;
    uint64_t threshold;
    uint64_t maximum;
};

int yb_validate_mapping(const struct yb_mapping_config *config);
int yb_validate_nlq(const struct yb_nlq_config *config);
uint32_t yb_abi_version(void);
uint64_t yb_sizeof_mapping_config(void);
uint64_t yb_sizeof_nlq_config(void);
uint64_t yb_sizeof_component_mapping(void);
uint64_t yb_sizeof_segment(void);

/* Outputs are unchanged on failure. Metadata is revalidated at each call;
 * callers must not mutate it concurrently. Chroma samples include an explicit
 * prepared luma guide, not an implicit full-resolution luma fetch.
 */
int yb_map_sample(const struct yb_mapping_config *config, int32_t component,
                  const int64_t samples[YB_COMPONENTS], uint16_t *output);
int yb_nlq(const struct yb_nlq_config *config, int64_t sample, int64_t *output);
int yb_compose_residual(int64_t mapped, int64_t residual, int32_t output_depth,
                        uint16_t *output);
int yb_compose(const struct yb_nlq_config *config, int64_t mapped,
                int64_t sample, int32_t output_depth, uint16_t *output);

/* Bounded same-count planar chunk, with all metadata/codes checked before any
 * output write. All three BL arrays are required; Y is the explicit MMR guide
 * for chroma and unused luma-channel Cb/Cr may be zero arrays. Count 1..65536.
 * Enabled is exactly 0/1. Disabled requires both nlq and EL to be NULL, not an
 * ignored extra layer. Outputs must not overlap each other, inputs or configs.
 * Pointers must be aligned and back buffers of at least count elements.
 * Caller-owned inputs/configs must remain stable throughout the call.
 * Validated NLQ results fit int32; sum remains signed and unclipped.
 */
int yb_process_chunk(const struct yb_mapping_config *map,
                     const struct yb_nlq_config *nlq, int32_t component,
                     const uint16_t *y, const uint16_t *cb, const uint16_t *cr,
                     const uint16_t *el, uint32_t count, int32_t enabled,
                     int32_t output_depth, uint16_t *mapped, int32_t *residual,
                     int32_t *sum, uint16_t *reconstructed);

#ifdef __cplusplus
}
#endif
#endif
