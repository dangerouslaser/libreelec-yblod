/*
 * Transactional HEVC QSV Dolby metadata association.
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Original project-owned integration code, adapting the ownership algorithms
 * qualified by the earlier QSV association and independent-context fixtures.
 * Included only by a GPL/version3-enabled FFmpeg build.
 */
#ifndef AVCODEC_QSV_DOVI_H
#define AVCODEC_QSV_DOVI_H

#include "dovi_rpu.h"
#include "h2645_parse.h"
#include "libavutil/mem.h"
#include "libavutil/refstruct.h"

#define QSV_DOVI_MAX 64

typedef struct QSVDOVIEntry {
    uint64_t token;
    int64_t pts, duration;
    AVBufferRef *metadata, *rpu;
} QSVDOVIEntry;

typedef struct QSVDOVIContext {
    DOVIContext active, prepared;
    H2645Packet nals;
    QSVDOVIEntry entries[QSV_DOVI_MAX], pending;
    unsigned count;
    uint64_t next;
    const uint8_t *remaining_data;
    int remaining_size;
    int failed;
} QSVDOVIContext;

static void qsv_dovi_entry_unref(QSVDOVIEntry *entry)
{
    av_buffer_unref(&entry->metadata);
    av_buffer_unref(&entry->rpu);
    *entry = (QSVDOVIEntry){0};
}

/* The native parser mutates refstructs in place: replacement is not cloning. */
static int qsv_dovi_clone(const DOVIContext *src, DOVIContext *out)
{
    DOVIContext copy = *src;
    int mapping = -1;
    for (int i = 0; i <= DOVI_MAX_DM_ID; i++)
        if (src->mapping && src->mapping == src->vdr[i])
            mapping = i;
    if ((src->mapping && mapping < 0) ||
        (src->color && src->color != src->dm && src->color != &ff_dovi_color_default))
        return AVERROR(EINVAL);
    memset(copy.vdr, 0, sizeof(copy.vdr));
    copy.dm = NULL;
    copy.ext_blocks = NULL;
    copy.mapping = NULL;
    copy.color = NULL;
    copy.rpu_buf = NULL;
    copy.rpu_buf_sz = 0;
    for (int i = 0; i <= DOVI_MAX_DM_ID; i++) {
        if (!src->vdr[i])
            continue;
        copy.vdr[i] = av_refstruct_allocz(sizeof(*copy.vdr[i]));
        if (!copy.vdr[i])
            goto nomem;
        *copy.vdr[i] = *src->vdr[i];
    }
    if (src->dm) {
        copy.dm = av_refstruct_allocz(sizeof(*copy.dm));
        if (!copy.dm)
            goto nomem;
        *copy.dm = *src->dm;
    }
    if (src->ext_blocks) {
        copy.ext_blocks = av_refstruct_allocz(sizeof(*copy.ext_blocks));
        if (!copy.ext_blocks)
            goto nomem;
        *copy.ext_blocks = *src->ext_blocks;
    }
    if (mapping >= 0)
        copy.mapping = copy.vdr[mapping];
    if (src->color)
        copy.color = src->color == &ff_dovi_color_default ? &ff_dovi_color_default : copy.dm;
    *out = copy;
    return 0;
nomem:
    ff_dovi_ctx_unref(&copy);
    return AVERROR(ENOMEM);
}

/* Header preflight prevents the splitter silently discarding malformed NALs. */
static int qsv_dovi_annexb_headers(const uint8_t *data, int size)
{
    int start = -1, count = 0;
    for (int i = 0; i < size - 2; i++) {
        if (data[i] || data[i + 1] || data[i + 2] != 1)
            continue;
        if (start < 0) {
            for (int j = 0; j < i; j++)
                if (data[j])
                    return AVERROR_INVALIDDATA;
        } else if (i - start < 2) {
            return AVERROR_INVALIDDATA;
        }
        start = i + 3;
        if (size - start < 2 || (data[start] & 0x80) || !(data[start + 1] & 7))
            return AVERROR_INVALIDDATA;
        count++;
        i = start + 1;
    }
    return count ? count : AVERROR_INVALIDDATA;
}

/* Restricted complete, single layer-zero picture. UNSPEC63 is opaque EL. */
static int qsv_dovi_admit(QSVDOVIContext *s, const AVPacket *pkt, H2645NAL **rpu)
{
    int first = 0, seen_vcl = 0, trailer = 0, ended = 0, nal_count, ret;
    int picture_type = -1, picture_temporal = -1;
    *rpu = NULL;
    if (!pkt->data || pkt->size <= 0 || pkt->size > 64 * 1024 * 1024)
        return AVERROR_INVALIDDATA;
    nal_count = qsv_dovi_annexb_headers(pkt->data, pkt->size);
    if (nal_count < 0)
        return nal_count;
    ret = ff_h2645_packet_split(&s->nals, pkt->data, pkt->size, s->active.logctx,
                               0, AV_CODEC_ID_HEVC, 0);
    if (ret < 0)
        return ret;
    if (s->nals.nb_nals != nal_count)
        return AVERROR_INVALIDDATA;
    for (int i = 0; i < s->nals.nb_nals; i++) {
        H2645NAL *nal = &s->nals.nals[i];
        if (nal->nuh_layer_id || nal->size < 2)
            return AVERROR_INVALIDDATA;
        if (ended && nal->type != 36 && nal->type != 37)
            return AVERROR_INVALIDDATA;
        if (nal->type <= 31) {
            if (trailer || nal->size < 3 || nal->size_bits <= 16)
                return AVERROR_INVALIDDATA;
            if (nal->data[2] & 0x80) {
                if (++first != 1)
                    return AVERROR_INVALIDDATA;
                picture_type = nal->type;
                picture_temporal = nal->temporal_id;
            } else if (!first) {
                return AVERROR_INVALIDDATA;
            }
            if (nal->type != picture_type || nal->temporal_id != picture_temporal)
                return AVERROR_INVALIDDATA;
            seen_vcl = 1;
        } else if (nal->type == 62) {
            if (!seen_vcl || nal->size <= 2 || nal->temporal_id)
                return AVERROR_INVALIDDATA;
            trailer = 1;
        } else if (nal->type == 63) {
            if (!seen_vcl || trailer)
                return AVERROR_INVALIDDATA;
        } else if (nal->type == 36 || nal->type == 37 || nal->type == 40) {
            if (!seen_vcl)
                return AVERROR_INVALIDDATA;
            trailer = 1;
            if (nal->type != 40)
                ended = 1;
        } else if ((nal->type >= 32 && nal->type <= 35) || nal->type == 39) {
            if (seen_vcl || trailer)
                return AVERROR_INVALIDDATA;
        } else {
            return AVERROR_INVALIDDATA;
        }
    }
    if (first != 1)
        return AVERROR_INVALIDDATA;
    /* Exactly the native backwards selection, including its i > 0 bound. */
    for (int i = s->nals.nb_nals - 1; i > 0; i--) {
        H2645NAL *nal = &s->nals.nals[i];
        if (nal->type == 62 && nal->size > 2 && !nal->nuh_layer_id && !nal->temporal_id) {
            *rpu = nal;
            break;
        }
    }
    return 0;
}

static void qsv_dovi_cancel(QSVDOVIContext *s)
{
    if (s->pending.token)
        s->next = s->pending.token;
    qsv_dovi_entry_unref(&s->pending);
    ff_dovi_ctx_unref(&s->prepared);
    s->remaining_data = NULL;
    s->remaining_size = 0;
}

static int qsv_dovi_prepare(QSVDOVIContext *s, const AVPacket *pkt, int err_recognition)
{
    H2645NAL *rpu;
    AVDOVIMetadata *metadata = NULL;
    DOVIContext candidate = {0};
    QSVDOVIEntry entry = {0};
    size_t cfg_size;
    const uint8_t *cfg;
    int ret;
    if (s->failed)
        return AVERROR_INVALIDDATA;
    if (s->pending.token)
        return pkt->data == s->remaining_data && pkt->size == s->remaining_size ?
               0 : AVERROR_INVALIDDATA;
    if (s->count == QSV_DOVI_MAX || s->next >= INT64_MAX)
        return AVERROR(ENOSPC);
    ret = qsv_dovi_admit(s, pkt, &rpu);
    if (ret < 0)
        return ret;
    ret = qsv_dovi_clone(&s->active, &candidate);
    if (ret < 0)
        return ret;
    cfg = av_packet_get_side_data(pkt, AV_PKT_DATA_DOVI_CONF, &cfg_size);
    if (cfg && cfg_size >= sizeof(candidate.cfg))
        candidate.cfg = *(const AVDOVIDecoderConfigurationRecord *)cfg;
    if (rpu) {
        /* Native ignores parse errors but retains the resulting parser state. */
        ret = ff_dovi_rpu_parse(&candidate, rpu->data + 2, rpu->size - 2, err_recognition);
        if (ret >= 0) {
            entry.rpu = av_buffer_alloc(rpu->raw_size - 2);
            if (!entry.rpu) {
                ret = AVERROR(ENOMEM);
                goto fail;
            }
            memcpy(entry.rpu->data, rpu->raw_data + 2, rpu->raw_size - 2);
        }
    }
    ret = ff_dovi_get_metadata(&candidate, &metadata);
    if (ret < 0)
        goto fail;
    if (ret) {
        entry.metadata = av_buffer_create((uint8_t *)metadata, ret, NULL, NULL, 0);
        if (!entry.metadata) {
            av_free(metadata);
            ret = AVERROR(ENOMEM);
            goto fail;
        }
    }
    entry.token = s->next + 1;
    entry.pts = pkt->pts;
    entry.duration = pkt->duration;
    s->pending = entry;
    s->prepared = candidate;
    s->remaining_data = pkt->data;
    s->remaining_size = pkt->size;
    return 0;
fail:
    qsv_dovi_entry_unref(&entry);
    ff_dovi_ctx_unref(&candidate);
    return ret;
}

/* Called only for real MFX consumption, before processing any returned frame. */
static int qsv_dovi_consume(QSVDOVIContext *s, unsigned consumed)
{
    if (!s->pending.token || consumed > (unsigned)s->remaining_size)
        return AVERROR_INVALIDDATA;
    s->remaining_data += consumed;
    s->remaining_size -= consumed;
    if (s->remaining_size)
        return 0;
    s->entries[s->count++] = s->pending;
    s->next = s->pending.token;
    s->pending = (QSVDOVIEntry){0};
    ff_dovi_ctx_replace(&s->active, &s->prepared);
    ff_dovi_ctx_unref(&s->prepared);
    return 0;
}

static int qsv_dovi_output(QSVDOVIContext *s, uint64_t token, AVFrame *frame)
{
    QSVDOVIEntry *entry = NULL;
    for (unsigned i = 0; i < s->count; i++)
        if (s->entries[i].token == token) {
            entry = &s->entries[i];
            break;
        }
    if (!entry || !token) {
        s->failed = 1;
        return AVERROR_INVALIDDATA;
    }
    av_frame_remove_side_data(frame, AV_FRAME_DATA_DOVI_METADATA);
    av_frame_remove_side_data(frame, AV_FRAME_DATA_DOVI_RPU_BUFFER);
    for (int i = 0; i < 2; i++) {
        AVBufferRef *buf = i ? entry->rpu : entry->metadata;
        AVBufferRef *ref;
        if (!buf)
            continue;
        ref = av_buffer_ref(buf);
        if (!ref)
            return AVERROR(ENOMEM);
        if (!av_frame_new_side_data_from_buf(frame, i ? AV_FRAME_DATA_DOVI_RPU_BUFFER :
                                                       AV_FRAME_DATA_DOVI_METADATA, ref)) {
            av_buffer_unref(&ref);
            return AVERROR(ENOMEM);
        }
    }
    frame->pts = entry->pts;
    frame->duration = entry->duration;
    qsv_dovi_entry_unref(entry);
    for (unsigned i = entry - s->entries; i + 1 < s->count; i++)
        s->entries[i] = s->entries[i + 1];
    s->entries[--s->count] = (QSVDOVIEntry){0};
    return 0;
}

/* Caller must discard/close the old MFX output generation before seek reuse. */
static void qsv_dovi_flush(QSVDOVIContext *s)
{
    qsv_dovi_cancel(s);
    for (unsigned i = 0; i < s->count; i++)
        qsv_dovi_entry_unref(&s->entries[i]);
    s->count = 0;
    ff_dovi_ctx_flush(&s->active);
    s->failed = 0;
}

static void qsv_dovi_uninit(QSVDOVIContext *s)
{
    qsv_dovi_flush(s);
    ff_dovi_ctx_unref(&s->active);
    ff_h2645_packet_uninit(&s->nals);
}
#endif
