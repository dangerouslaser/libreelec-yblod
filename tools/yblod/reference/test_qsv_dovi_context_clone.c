/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "libavutil/refstruct.h"
#include "libavutil/mem.h"
#include <assert.h>
#include <stdio.h>
static unsigned attempts, live, freed, fail_at;
static void free_count(AVRefStructOpaque opaque, void *obj)
{ (void)opaque; (void)obj; --live; ++freed; }
static void *allocate(size_t size)
{
    if (++attempts == fail_at) return NULL;
    void *p = av_refstruct_alloc_ext(size, 0, NULL, free_count);
    if (p) ++live;
    return p;
}
#define QDA_REF_ALLOC allocate
#include "qsv_dovi_context_clone.h"
int main(void)
{
    DOVIContext src = {.enable = -1}, copy = {0}, sentinel = {.enable = 99};
    src.cfg.dv_profile = 7; src.header.vdr_bit_depth = 12;
    src.vdr[0] = av_refstruct_allocz(sizeof(*src.vdr[0]));
    src.vdr[15] = av_refstruct_allocz(sizeof(*src.vdr[15]));
    src.dm = av_refstruct_allocz(sizeof(*src.dm));
    src.ext_blocks = av_refstruct_allocz(sizeof(*src.ext_blocks));
    assert(src.vdr[0] && src.vdr[15] && src.dm && src.ext_blocks);
    src.mapping = src.vdr[15]; src.color = src.dm;
    src.rpu_buf = av_malloc(32); src.rpu_buf_sz = 32;
    assert(src.rpu_buf); src.rpu_buf[0] = 123;
    src.vdr[15]->vdr_rpu_id = 15; src.ext_blocks->num_static = 2;
    for (unsigned fail = 1; fail <= 4; ++fail) {
        attempts = 0; fail_at = fail; unsigned old = freed;
        assert(qda_context_clone(&src, &sentinel) == AVERROR(ENOMEM));
        assert(sentinel.enable == 99 && !sentinel.dm && !sentinel.vdr[0]);
        assert(!live && freed - old == fail - 1);
        assert(src.mapping == src.vdr[15] && src.color == src.dm);
    }
    fail_at = 0; attempts = 0;
    assert(!qda_context_clone(&src, &copy) && live == 4);
    assert(copy.mapping == copy.vdr[15] && copy.color == copy.dm);
    assert(!copy.rpu_buf && !copy.rpu_buf_sz && src.rpu_buf[0] == 123);
    assert(copy.enable == -1 && copy.cfg.dv_profile == 7 && copy.header.vdr_bit_depth == 12);
    copy.vdr[15]->vdr_rpu_id = 3; copy.dm->ycc_to_rgb_offset[0].num = 10;
    copy.ext_blocks->num_static = 4;
    assert(src.vdr[15]->vdr_rpu_id == 15 && !src.dm->ycc_to_rgb_offset[0].num);
    assert(src.ext_blocks->num_static == 2);
    ff_dovi_ctx_replace(&src, &copy); ff_dovi_ctx_unref(&copy);
    assert(live == 4 && src.vdr[15]->vdr_rpu_id == 3 && src.ext_blocks->num_static == 4);
    assert(!qda_context_clone(&src, &copy));
    copy.vdr[15]->vdr_rpu_id = 8;
    assert(src.vdr[15]->vdr_rpu_id == 3); ff_dovi_ctx_unref(&copy);
    src.color = &ff_dovi_color_default;
    assert(!qda_context_clone(&src, &copy) && copy.color == &ff_dovi_color_default);
    ff_dovi_ctx_unref(&copy);
    src.mapping = (const AVDOVIDataMapping *)&sentinel;
    assert(qda_context_clone(&src, &copy) == AVERROR(EINVAL));
    src.mapping = src.vdr[15];
    src.color = (const AVDOVIColorMetadata *)&sentinel;
    assert(qda_context_clone(&src, &copy) == AVERROR(EINVAL));
    src.color = &ff_dovi_color_default;
    ff_dovi_ctx_unref(&src); assert(!live);
    DOVIContext empty = {0};
    unsigned before = attempts;
    assert(!qda_context_clone(&empty, &copy) && attempts == before);
    assert(!copy.mapping && !copy.color && !copy.ext_blocks && !copy.dm);
    ff_dovi_ctx_unref(&copy);
    puts("QSV DOVI context clone PASS: independent state, failure ownership, publication");
    return 0;
}
