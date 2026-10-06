#ifndef YB_NATIVE_GPU_DIAG_NLQ_LUT_H
#define YB_NATIVE_GPU_DIAG_NLQ_LUT_H
#include "native_composer.h"
#include <stddef.h>
enum { YB_DIAG_NLQ_CODES=1024, YB_DIAG_NLQ_ENTRIES=3072 };
#define YB_DIAG_NLQ_SHADER_MARKER "#define YB_DIAG_NLQ_LUT 1\n"
int yb_diag_nlq_lut_build(const struct yb_nlq_config configs[3],int32_t out[YB_DIAG_NLQ_ENTRIES]);
int yb_diag_nlq_configs_equal(const struct yb_nlq_config a[3],const struct yb_nlq_config b[3]);
int yb_diag_nlq_shader_patch(const char *source,size_t bytes,char **out,size_t *out_bytes);
void yb_diag_nlq_record_build(void);
void yb_diag_nlq_record_hit(void);
void yb_diag_nlq_record_upload(void);
void yb_diag_nlq_record_shader(void);
void yb_diag_nlq_report(void);
#endif
