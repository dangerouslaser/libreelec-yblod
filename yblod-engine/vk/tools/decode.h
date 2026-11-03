/* Test-tool decoding: a Dolby Vision file through ffmpeg-yblod VAAPI, the BL
 * and (Profile 7) the EL split with dovi_split and decoded on one VADisplay,
 * paired in order as mpv's f_enhancement_pair does. Headless, render node. */
#pragma once
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavcodec/bsf.h>
#include <libavutil/hwcontext.h>
#include <libavutil/dovi_meta.h>
#include <libavutil/hwcontext_vaapi.h>
#include <va/va.h>

struct dv_decoder {
    AVFormatContext *fmt;
    int stream;
    AVBufferRef *device;
    VADisplay display;
    AVBSFContext *bsf[2];       /* BL (+RPU), EL; NULL if single layer */
    AVCodecContext *dec[2];     /* BL, EL (EL NULL if single layer) */
    AVFrame *pending[2];
    int profile, el_present, eof;
    int mel_decided;             /* first BL RPU, reset on every open */
    int split;                  /* no dovi_split: decode.c splits the layers */
    AVRational time_base;
};

struct dv_pair {
    AVFrame *bl, *el;           /* VAAPI frames; el NULL if none */
    VASurfaceID bl_surface, el_surface;
    const AVFrameSideData *dovi; /* AV_FRAME_DATA_DOVI_METADATA (BL, else EL) */
};

int dv_decoder_open(struct dv_decoder *d, const char *path, const char *node, double start);
/* 1: a pair; 0: end; <0: error. Caller frees with dv_pair_free. */
int dv_decoder_next(struct dv_decoder *d, struct dv_pair *p);
void dv_pair_free(struct dv_pair *p);
void dv_decoder_close(struct dv_decoder *d);

/* Same Annex II/no-residual decision as production mpv. Call only on parsed
 * FFmpeg metadata belonging to the base layer, never EL-only metadata. */
static inline int dv_decoder_metadata_no_residual(const AVDOVIMetadata *md)
{
    const AVDOVIRpuDataHeader *h = av_dovi_get_header(md);
    const AVDOVIDataMapping *m = av_dovi_get_mapping(md);
    if (h->disable_residual_flag == 1)
        return 1;
    if (h->coef_data_type || h->coef_log2_denom > 32 ||
        h->bl_bit_depth != 10 || h->el_bit_depth != 10 ||
        h->vdr_bit_depth != 12 || m->nlq_method_idc != AV_DOVI_NLQ_LINEAR_DZ)
        return 0;
    uint64_t maximum = UINT64_C(1) << h->coef_log2_denom;
    for (int c = 0; c < 3; c++) {
        const AVDOVINLQParams *n = &m->nlq[c];
        if (n->nlq_offset || n->vdr_in_max != maximum ||
            n->linear_deadzone_slope || n->linear_deadzone_threshold)
            return 0;
    }
    return 1;
}
