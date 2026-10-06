/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef QSV_DOVI_CONTEXT_CLONE_H
#define QSV_DOVI_CONTEXT_CLONE_H
#include "libavcodec/dovi_rpu.h"
#include "libavutil/refstruct.h"
#include "libavutil/error.h"
#include <string.h>
#ifndef QDA_REF_ALLOC
#define QDA_REF_ALLOC av_refstruct_allocz
#endif
/* Source must be a live decoder context; output must be empty and independent.
 * Parser scratch is deliberately not shared; it contains no resolved state. */
static inline int qda_context_clone(const DOVIContext *src, DOVIContext *out)
{
    int mapping = -1;
    if (!src || !out || src == out)
        return AVERROR(EINVAL);
    for (int i = 0; i <= DOVI_MAX_DM_ID; ++i)
        if (src->mapping && src->mapping == src->vdr[i])
            mapping = i;
    if ((src->mapping && mapping < 0) ||
        (src->color && src->color != src->dm && src->color != &ff_dovi_color_default))
        return AVERROR(EINVAL);
    DOVIContext copy = *src;
    copy.dm = NULL; copy.ext_blocks = NULL; copy.mapping = NULL; copy.color = NULL;
    copy.rpu_buf = NULL; copy.rpu_buf_sz = 0;
    memset(copy.vdr, 0, sizeof(copy.vdr));
    for (int i = 0; i <= DOVI_MAX_DM_ID; ++i) {
        if (!src->vdr[i]) continue;
        copy.vdr[i] = QDA_REF_ALLOC(sizeof(*copy.vdr[i]));
        if (!copy.vdr[i]) goto nomem;
        *copy.vdr[i] = *src->vdr[i];
    }
    if (src->dm) {
        copy.dm = QDA_REF_ALLOC(sizeof(*copy.dm));
        if (!copy.dm) goto nomem;
        *copy.dm = *src->dm;
    }
    if (src->ext_blocks) {
        copy.ext_blocks = QDA_REF_ALLOC(sizeof(*copy.ext_blocks));
        if (!copy.ext_blocks) goto nomem;
        *copy.ext_blocks = *src->ext_blocks;
    }
    if (mapping >= 0) copy.mapping = copy.vdr[mapping];
    if (src->color) copy.color = src->color == &ff_dovi_color_default ?
        &ff_dovi_color_default : copy.dm;
    *out = copy;
    return 0;
nomem:
    ff_dovi_ctx_unref(&copy);
    return AVERROR(ENOMEM);
}
#endif
