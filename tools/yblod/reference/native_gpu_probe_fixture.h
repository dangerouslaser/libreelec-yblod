#ifndef YB_NATIVE_GPU_PROBE_FIXTURE_H
#define YB_NATIVE_GPU_PROBE_FIXTURE_H
#include "native_composer.h"
#include "native_gpu_guard.h"
#define YB_PROBE_MAX_SAMPLES 4096U
#define YB_PROBE_METADATA_WORDS 93U
struct yb_probe_sample { uint32_t y, cb, cr, el; };
struct yb_probe_result { int32_t mapped, residual, sum, reconstructed; };
struct yb_probe_fixture {
    uint32_t count;
    int32_t component, enabled, output_depth;
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq;
    struct yb_probe_sample samples[YB_PROBE_MAX_SAMPLES];
    struct yb_gpu_width_report width;
    int polynomial_only;
};
/* Strict bounded little-endian diagnostic format, never a media/RPU parser. */
int yb_probe_load(const char *path, struct yb_probe_fixture *fixture);
int yb_probe_cpu(const struct yb_probe_fixture *, struct yb_probe_result *);
void yb_probe_metadata(const struct yb_probe_fixture *, int64_t words[YB_PROBE_METADATA_WORDS]);
#endif
