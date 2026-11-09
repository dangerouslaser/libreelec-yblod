/* The libavutil functions the ported CB1 tests call (the engine doesn't link
 * libavutil), the failure counter, and the runner `cargo test` calls
 * (src/hdr10plus.rs). Test-only: nothing in the library references these.
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include <libavutil/dovi_meta.h>
#include <libavutil/hdr_dynamic_metadata.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned failures, checks;

void yb_test_check(int ok, const char *what, const char *file, int line)
{
    checks++;
    if (!ok) {
        failures++;
        fprintf(stderr, "%s:%d: check failed: %s\n", file, line, what);
    }
}

void *av_memdup(const void *p, size_t size)
{
    void *q = malloc(size ? size : 1);
    if (q && p)
        memcpy(q, p, size);
    return q;
}

void av_free(void *p) { free(p); }

AVDynamicHDRPlus *av_dynamic_hdr_plus_alloc(size_t *size)
{
    if (size)
        *size = sizeof(AVDynamicHDRPlus);
    return calloc(1, sizeof(AVDynamicHDRPlus));
}

/* libavutil/dovi_meta.c's layout */
typedef struct {
    AVDOVIMetadata metadata;
    AVDOVIRpuDataHeader header;
    AVDOVIDataMapping mapping;
    AVDOVIColorMetadata color;
    AVDOVIDmData ext_blocks[AV_DOVI_MAX_EXT_BLOCKS];
} dovi_internal;

AVDOVIMetadata *av_dovi_metadata_alloc(size_t *size)
{
    dovi_internal *d = calloc(1, sizeof(*d));
    if (!d)
        return NULL;
    if (size)
        *size = sizeof(*d);
    d->metadata.header_offset = offsetof(dovi_internal, header);
    d->metadata.mapping_offset = offsetof(dovi_internal, mapping);
    d->metadata.color_offset = offsetof(dovi_internal, color);
    d->metadata.ext_block_offset = offsetof(dovi_internal, ext_blocks);
    d->metadata.ext_block_size = sizeof(AVDOVIDmData);
    return &d->metadata;
}

int yb_cb1_test_transport(void);
int yb_cb1_test_curve(void);
int yb_cb1_test_dv_hdr10plus(void);
int yb_cb1_test_dovi(void);
int yb_test_describe(void);
int yb_test_yblod(void);

/* Every C test; returns the failures (checks counted in *count). */
unsigned dvvk_test_hdr10plus_c(unsigned *count)
{
    failures = checks = 0;
    yb_cb1_test_transport();
    yb_cb1_test_curve();
    yb_cb1_test_dv_hdr10plus();
    yb_cb1_test_dovi();
    yb_test_describe();
    yb_test_yblod();
    if (count)
        *count = checks;
    return failures;
}
