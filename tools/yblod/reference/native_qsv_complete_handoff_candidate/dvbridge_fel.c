/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Split and hardware-decode the enhancement layer; pair surfaces by exact presentation time. */
#include "dvbridge_fel.h"
#include "dvbridge_fel_qsv_tokens.h"
#include <libavcodec/bsf.h>
#include <libavutil/hwcontext.h>
#include <libavutil/intreadwrite.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

#define QUEUE_MAX 32
#define PACKET_BYTES_MAX (64u * 1024u * 1024u)
#define MAP_MAX (QUEUE_MAX * 2)

/* Independently coded layers can have different decode
 * order and IDR boundaries. Use FFmpeg's HEVC parser rather than assigning
 * the BL packet timestamp blindly to the encapsulated EL access unit. */
struct picture_order {
    AVCodecParserContext *parser;
    AVCodecContext *context;
    int64_t offset, maximum;
    bool seen;
};

static bool picture_identity(struct picture_order *order, const AVPacket *packet, int64_t *identity)
{
    uint8_t *output;
    int output_size;
    order->parser->output_picture_number = INT_MIN;
    int used = av_parser_parse2(order->parser, order->context, &output, &output_size,
                               packet->data, packet->size, packet->pts, packet->dts, packet->pos);
    int poc = order->parser->output_picture_number;
    if (used != packet->size || output_size <= 0 || poc == INT_MIN)
        return false;
    if (order->seen && poc == 0 && order->parser->key_frame == 1) {
        if (order->maximum == INT64_MAX)
            return false;
        order->offset = order->maximum + 1;
    }
    if (poc > 0 && order->offset > INT64_MAX - poc)
        return false;
    *identity = order->offset + poc;
    if (!order->seen || *identity > order->maximum)
        order->maximum = *identity;
    order->seen = true;
    return true;
}

struct dvbridge_fel {
    AVBSFContext *split;
    AVBSFContext *qsv_normalizer;
    bool qsv_configuration_present;
    unsigned qsv_inband_headers;
    AVCodecContext *decoder;
    AVPacket *packets[QUEUE_MAX];
    AVFrame *frames[QUEUE_MAX];
    unsigned num_packets, num_frames;
    size_t packet_bytes;
    bool opened, failed, draining, sent_eof, eof;
    struct picture_order base_order, enhancement_order;
    int64_t packet_order[QUEUE_MAX];
    struct dvbridge_qsv_properties packet_properties[QUEUE_MAX];
    struct { int64_t order, pts; } times[MAP_MAX];
    unsigned num_times;
    bool synchronizing;
    int64_t anchor_pts;
    unsigned preroll_packets;
    bool qsv;
    AVBufferRef *source_device;
    struct dvbridge_qsv_tokens tokens;
    AVRational source_time_base;
    uint64_t qsv_mapped_frames;
    uint64_t paired_frames;
    AVBufferRef *mapping_source, *mapping_frames;
};

static unsigned qsv_parameter_headers(const AVPacket *packet)
{
    unsigned mask = 0;
    for (int i = 0; i + 4 < packet->size; ++i) {
        int header = -1;
        if (!packet->data[i] && !packet->data[i+1] && !packet->data[i+2] && packet->data[i+3] == 1)
            header = i + 4;
        else if (!packet->data[i] && !packet->data[i+1] && packet->data[i+2] == 1)
            header = i + 3;
        if (header >= 0 && header + 1 < packet->size &&
            !(packet->data[header] & 0x80) && (packet->data[header+1] & 7)) {
            int type = (packet->data[header] >> 1) & 63;
            if (type >= 32 && type <= 34)
                mask |= 1u << (type - 32);
        }
    }
    return mask;
}

static bool qsv_configuration_has_parameters(const AVCodecParameters *parameters)
{
    AVPacket packet = {.data = parameters->extradata, .size = parameters->extradata_size};
    return packet.data && packet.size > 0 && qsv_parameter_headers(&packet) == 7;
}

static enum AVPixelFormat hardware_format(AVCodecContext *ctx, const enum AVPixelFormat *formats)
{
    /* QSV allocates its own hardware pool from the derived device. Never
     * select its advertised software formats. */
    if (ctx->hw_device_ctx &&
        ((AVHWDeviceContext *)ctx->hw_device_ctx->data)->type == AV_HWDEVICE_TYPE_QSV) {
        for (; *formats != AV_PIX_FMT_NONE; ++formats)
            if (*formats == AV_PIX_FMT_QSV)
                return AV_PIX_FMT_QSV;
        return AV_PIX_FMT_NONE;
    }
    bool found = false;
    for (; *formats != AV_PIX_FMT_NONE; ++formats)
        found |= *formats == AV_PIX_FMT_VAAPI;
    if (!found || !ctx->hw_device_ctx)
        return AV_PIX_FMT_NONE;
    AVBufferRef *frames = NULL;
    if (avcodec_get_hw_frames_parameters(ctx, ctx->hw_device_ctx, AV_PIX_FMT_VAAPI, &frames) < 0)
        return AV_PIX_FMT_NONE;
    AVHWFramesContext *hw = (void *)frames->data;
    hw->initial_pool_size += QUEUE_MAX + 4;
    if (av_hwframe_ctx_init(frames) < 0) {
        av_buffer_unref(&frames);
        return AV_PIX_FMT_NONE;
    }
    av_buffer_unref(&ctx->hw_frames_ctx);
    ctx->hw_frames_ctx = frames;
    return AV_PIX_FMT_VAAPI;
}

static void clear_queues(struct dvbridge_fel *f)
{
    for (unsigned i = 0; i < f->num_packets; ++i)
        av_packet_free(&f->packets[i]);
    for (unsigned i = 0; i < f->num_frames; ++i)
        av_frame_free(&f->frames[i]);
    f->num_packets = f->num_frames = 0;
    f->packet_bytes = 0;
    f->failed = f->draining = f->sent_eof = f->eof = false;
    f->num_times = 0;
    dvbridge_qsv_tokens_reset(&f->tokens);
    av_buffer_unref(&f->mapping_frames);
    av_buffer_unref(&f->mapping_source);
}

void dvbridge_fel_reset(struct dvbridge_fel *f)
{
    if (!f)
        return;
    clear_queues(f);
    f->synchronizing = true;
    f->anchor_pts = AV_NOPTS_VALUE;
    f->preroll_packets = 0;
    struct picture_order *orders[] = {&f->base_order, &f->enhancement_order};
    for (unsigned i = 0; i < 2; ++i) {
        struct picture_order *order = orders[i];
        av_parser_close(order->parser);
        order->parser = av_parser_init(AV_CODEC_ID_HEVC);
        if (order->parser)
            order->parser->flags = PARSER_FLAG_COMPLETE_FRAMES;
        else
            f->failed = true;
        order->offset = order->maximum = 0;
        order->seen = false;
    }
    if (f->split)
        av_bsf_flush(f->split);
    if (f->qsv_normalizer)
        av_bsf_flush(f->qsv_normalizer);
    f->qsv_inband_headers = 0;
    if (f->opened)
        avcodec_flush_buffers(f->decoder);
}

void dvbridge_fel_destroy(struct dvbridge_fel *f)
{
    if (!f)
        return;
    clear_queues(f);
    av_parser_close(f->base_order.parser);
    av_parser_close(f->enhancement_order.parser);
    avcodec_free_context(&f->base_order.context);
    avcodec_free_context(&f->enhancement_order.context);
    avcodec_free_context(&f->decoder);
    av_buffer_unref(&f->source_device);
    av_bsf_free(&f->split);
    av_bsf_free(&f->qsv_normalizer);
    free(f);
}

struct dvbridge_fel *dvbridge_fel_create(const AVCodecParameters *p, AVRational time_base)
{
    if (!p || p->codec_id != AV_CODEC_ID_HEVC || time_base.num <= 0 || time_base.den <= 0)
        return NULL;
    const char *option = getenv("DVBRIDGE_FEL_QSV");
    bool qsv;
    if (!dvbridge_qsv_option(option, &qsv))
        return NULL;
    /* A build without hevc_qsv fails explicitly when requested. No fallback. */
    const AVCodec *codec = qsv ? avcodec_find_decoder_by_name("hevc_qsv") :
                                avcodec_find_decoder(AV_CODEC_ID_HEVC);
    if (!codec)
        return NULL;
    struct dvbridge_fel *f = calloc(1, sizeof(*f));
    if (!f)
        return NULL;
    f->synchronizing = true;
    f->qsv = qsv;
    f->source_time_base = time_base;
    f->anchor_pts = AV_NOPTS_VALUE;
    if (av_bsf_list_parse_str("dovi_split=mode=el", &f->split) < 0 ||
        avcodec_parameters_copy(f->split->par_in, p) < 0)
        goto fail;
    f->split->time_base_in = time_base;
    if (av_bsf_init(f->split) < 0)
        goto fail;
    const AVCodecParameters *decoder_parameters = f->split->par_out;
    if (qsv) {
        const AVPacketSideData *configuration = av_packet_side_data_get(p->coded_side_data,
            p->nb_coded_side_data, AV_PKT_DATA_HEVC_CONF);
        f->qsv_configuration_present = configuration && configuration->size >= 23;
        if (av_bsf_alloc(av_bsf_get_by_name("hevc_mp4toannexb"), &f->qsv_normalizer) < 0 ||
            avcodec_parameters_copy(f->qsv_normalizer->par_in, f->split->par_out) < 0)
            goto fail;
        f->qsv_normalizer->time_base_in = time_base;
        if (av_bsf_init(f->qsv_normalizer) < 0)
            goto fail;
        if (f->qsv_configuration_present && !qsv_configuration_has_parameters(f->qsv_normalizer->par_out))
            goto fail;
        /* dovi_split keeps BL extradata when no separate EL configuration is
         * supplied. Preserve its initialized length parser, not those BL SPS. */
        if (!f->qsv_configuration_present) {
            av_freep(&f->qsv_normalizer->par_out->extradata);
            f->qsv_normalizer->par_out->extradata_size = 0;
        }
        decoder_parameters = f->qsv_normalizer->par_out;
    }
    f->decoder = avcodec_alloc_context3(codec);
    if (!f->decoder || avcodec_parameters_to_context(f->decoder, decoder_parameters) < 0)
        goto fail;
    f->decoder->pkt_timebase = qsv ? (AVRational){1, 90000} : time_base;
    f->decoder->get_format = hardware_format;
    f->decoder->thread_count = 1;
    if (qsv)
        f->decoder->extra_hw_frames = QUEUE_MAX + 4;
    struct picture_order *orders[] = {&f->base_order, &f->enhancement_order};
    const AVCodecParameters *parameters[] = {p, decoder_parameters};
    for (unsigned i = 0; i < 2; ++i) {
        orders[i]->parser = av_parser_init(AV_CODEC_ID_HEVC);
        orders[i]->context = avcodec_alloc_context3(NULL);
        if (!orders[i]->parser || !orders[i]->context ||
            avcodec_parameters_to_context(orders[i]->context, parameters[i]) < 0)
            goto fail;
        orders[i]->parser->flags = PARSER_FLAG_COMPLETE_FRAMES;
    }
    return f;
fail:
    dvbridge_fel_destroy(f);
    return NULL;
}

static bool receive_frames(struct dvbridge_fel *f)
{
    while (f->num_frames < QUEUE_MAX) {
        AVFrame *frame = av_frame_alloc();
        if (!frame)
            return false;
        int result = avcodec_receive_frame(f->decoder, frame);
        if (result < 0) {
            av_frame_free(&frame);
            if (result == AVERROR_EOF && f->qsv && f->tokens.count)
                return false;
            if (result == AVERROR_EOF)
                f->eof = true;
            return result == AVERROR(EAGAIN) || result == AVERROR_EOF;
        }
        /* Never trust reserved route markers propagated from input metadata. */
        if (av_dict_set(&frame->metadata, "dvbridge.el.qsv", NULL, 0) < 0 ||
            av_dict_set(&frame->metadata, "dvbridge.el.qsv_map_sequence", NULL, 0) < 0) {
            av_frame_free(&frame);
            return false;
        }
        if (f->qsv) {
            struct dvbridge_qsv_timestamp stamp;
            AVFrame *mapped = av_frame_alloc();
            if (!mapped || frame->format != AV_PIX_FMT_QSV ||
                frame->pts == AV_NOPTS_VALUE ||
                !dvbridge_qsv_token_take(&f->tokens, frame->pts, &stamp)) {
                av_frame_free(&mapped);
                av_frame_free(&frame);
                return false;
            }
            if (!frame->hw_frames_ctx) {
                av_frame_free(&mapped);
                av_frame_free(&frame);
                return false;
            }
            if (!f->mapping_source || f->mapping_source->data != frame->hw_frames_ctx->data) {
                av_buffer_unref(&f->mapping_frames);
                av_buffer_unref(&f->mapping_source);
                f->mapping_source = av_buffer_ref(frame->hw_frames_ctx);
                if (!f->mapping_source || av_hwframe_ctx_create_derived(&f->mapping_frames,
                        AV_PIX_FMT_VAAPI, f->source_device, frame->hw_frames_ctx,
                        AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT) < 0) {
                    av_frame_free(&mapped);
                    av_frame_free(&frame);
                    return false;
                }
            }
            mapped->format = AV_PIX_FMT_VAAPI;
            mapped->hw_frames_ctx = av_buffer_ref(f->mapping_frames);
            /* The direct QSV mapping retains the source AVFrame and child
             * VAAPI pool. No transfer/download or surface-ID-only borrowing. */
            if (!mapped->hw_frames_ctx ||
                av_hwframe_map(mapped, frame, AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT) < 0 ||
                av_frame_copy_props(mapped, frame) < 0 || !mapped->hw_frames_ctx ||
                mapped->format != AV_PIX_FMT_VAAPI ||
                ((AVHWFramesContext *)mapped->hw_frames_ctx->data)->device_ctx !=
                    (AVHWDeviceContext *)f->source_device->data) {
                av_frame_free(&mapped);
                av_frame_free(&frame);
                return false;
            }
            mapped->pts = mapped->best_effort_timestamp = stamp.pts;
            /* DTS is unknown for this POC-associated EL AU, as before. */
            mapped->pkt_dts = AV_NOPTS_VALUE;
            mapped->duration = stamp.duration;
            if (!stamp.properties_valid || mapped->width != stamp.properties.width ||
                mapped->height != stamp.properties.height ||
                stamp.properties.format != AV_PIX_FMT_YUV420P10LE ||
                (mapped->flags & AV_FRAME_FLAG_INTERLACED) || mapped->crop_top ||
                mapped->crop_bottom || mapped->crop_left || mapped->crop_right) {
                av_frame_free(&mapped);
                av_frame_free(&frame);
                return false;
            }
            mapped->chroma_location = stamp.properties.chroma_location;
            mapped->color_range = stamp.properties.color_range;
            mapped->color_primaries = stamp.properties.color_primaries;
            mapped->color_trc = stamp.properties.color_trc;
            mapped->colorspace = stamp.properties.colorspace;
            mapped->sample_aspect_ratio = (AVRational){stamp.properties.sar_num,
                                                       stamp.properties.sar_den};
            /* Match the existing VAAPI AVFrame convention: time_base is
             * unspecified; restored timestamps use the helper's externally
             * supplied source_time_base, not the QSV token time base. */
            mapped->time_base = (AVRational){0, 1};
            if (f->qsv_mapped_frames == INT64_MAX ||
                av_dict_set(&mapped->metadata, "dvbridge.el.qsv", "1", 0) < 0 ||
                av_dict_set_int(&mapped->metadata, "dvbridge.el.qsv_map_sequence",
                                f->qsv_mapped_frames + 1, 0) < 0) {
                av_frame_free(&mapped);
                av_frame_free(&frame);
                return false;
            }
            ++f->qsv_mapped_frames;
            av_frame_free(&frame);
            frame = mapped;
        }
        /* This timestamp was mapped from HEVC picture order before decoding,
         * not borrowed from the BL packet carrying this EL access unit. */
        if (frame->pts == AV_NOPTS_VALUE)
            frame->pts = frame->best_effort_timestamp;
        if (frame->format != AV_PIX_FMT_VAAPI || frame->pts == AV_NOPTS_VALUE) {
            av_frame_free(&frame);
            return false;
        }
        for (unsigned i = 0; i < f->num_frames; ++i) {
            if (f->frames[i]->pts == frame->pts) {
                av_frame_free(&frame);
                return false;
            }
        }
        f->frames[f->num_frames++] = frame;
    }
    return true;
}

static bool pump(struct dvbridge_fel *f)
{
    if (f->failed)
        return false;
    if (!f->opened)
        return true;
    if (!receive_frames(f))
        goto fail;
    while (f->num_packets && f->num_frames < QUEUE_MAX) {
        AVPacket *packet = f->packets[0];
        unsigned match = 0;
        while (match < f->num_times && f->times[match].order != f->packet_order[0])
            ++match;
        if (match == f->num_times) {
            if (f->draining)
                goto fail;
            break; /* A reference EL picture can precede its corresponding BL. */
        }
        packet->pts = f->times[match].pts;
        packet->dts = AV_NOPTS_VALUE;
        int64_t original_pts = packet->pts;
        if (f->qsv && !dvbridge_qsv_token_peek(&f->tokens, original_pts, &packet->pts))
            goto fail;
        int result = avcodec_send_packet(f->decoder, packet);
        int64_t token = packet->pts;
        packet->pts = original_pts;
        if (result == AVERROR(EAGAIN))
            break;
        if (result < 0)
            goto fail;
        if (f->qsv && !dvbridge_qsv_token_commit_properties(&f->tokens, token, original_pts,
                packet->duration, &f->packet_properties[0]))
            goto fail;
        --f->num_times;
        memmove(f->times + match, f->times + match + 1,
                (f->num_times - match) * sizeof(*f->times));
        f->packet_bytes -= packet->size;
        av_packet_free(&packet);
        --f->num_packets;
        memmove(f->packets, f->packets + 1, f->num_packets * sizeof(*f->packets));
        memmove(f->packet_order, f->packet_order + 1, f->num_packets * sizeof(*f->packet_order));
        memmove(f->packet_properties, f->packet_properties + 1,
                f->num_packets * sizeof(*f->packet_properties));
        if (!receive_frames(f))
            goto fail;
    }
    if (f->draining && !f->num_packets && !f->sent_eof && f->num_frames < QUEUE_MAX) {
        int result = avcodec_send_packet(f->decoder, NULL);
        if (result != AVERROR(EAGAIN)) {
            if (result < 0 && result != AVERROR_EOF)
                goto fail;
            f->sent_eof = true;
        }
        if (!receive_frames(f))
            goto fail;
    }
    return true;
fail:
    f->failed = true;
    return false;
}

bool dvbridge_fel_device(struct dvbridge_fel *f, AVBufferRef *device)
{
    if (!f || !device || ((AVHWDeviceContext *)device->data)->type != AV_HWDEVICE_TYPE_VAAPI)
        return false;
    if (f->opened)
        return (f->qsv ? f->source_device->data : f->decoder->hw_device_ctx->data) ==
                   device->data && pump(f);
    if (f->qsv) {
        f->source_device = av_buffer_ref(device);
        if (!f->source_device || av_hwdevice_ctx_create_derived(&f->decoder->hw_device_ctx,
                AV_HWDEVICE_TYPE_QSV, device, 0) < 0) {
            f->failed = true;
            return false;
        }
    } else {
        f->decoder->hw_device_ctx = av_buffer_ref(device);
    }
    AVDictionary *options = NULL;
    if (f->qsv && av_dict_set_int(&options, "async_depth", 1, 0) < 0) {
        f->failed = true;
        return false;
    }
    int result = f->decoder->hw_device_ctx ?
        avcodec_open2(f->decoder, f->decoder->codec, f->qsv ? &options : NULL) : AVERROR(EINVAL);
    bool unused = av_dict_count(options) != 0;
    av_dict_free(&options);
    if (result < 0 || unused) {
        f->failed = true;
        return false;
    }
    f->opened = true;
    return pump(f);
}


static bool normalize_qsv_packet(struct dvbridge_fel *f, AVPacket *packet)
{
    if (!f->qsv)
        return true;
    if (!f->qsv_normalizer || av_bsf_send_packet(f->qsv_normalizer, packet) < 0 ||
        av_bsf_receive_packet(f->qsv_normalizer, packet) < 0)
        return false;
    /* MP4-to-AnnexB is a non-buffering one-packet filter. Inspect only NAL
     * headers; payloads, timestamp properties and picture order are retained. */
    f->qsv_inband_headers |= qsv_parameter_headers(packet);
    return true;
}

bool dvbridge_fel_submit(struct dvbridge_fel *f, const AVPacket *packet)
{
    if (!f || !packet || f->failed || f->draining || packet->size <= 0 ||
        packet->pts == AV_NOPTS_VALUE)
        return false;
    int64_t base_identity;
    if (f->num_times == MAP_MAX || !picture_identity(&f->base_order, packet, &base_identity))
        goto fail;
    for (unsigned i = 0; i < f->num_times; ++i)
        if (f->times[i].order == base_identity)
            goto fail;
    f->times[f->num_times].order = base_identity;
    f->times[f->num_times++].pts = packet->pts;
    AVPacket *copy = av_packet_clone(packet);
    if (!copy)
        goto fail;
    int result = av_bsf_send_packet(f->split, copy);
    av_packet_free(&copy);
    if (result < 0)
        goto fail;
    while (true) {
        copy = av_packet_alloc();
        if (!copy)
            goto fail;
        result = av_bsf_receive_packet(f->split, copy);
        if (result < 0) {
            av_packet_free(&copy);
            if (result == AVERROR(EAGAIN))
                return pump(f);
            goto fail;
        }
        if (!normalize_qsv_packet(f, copy) || f->num_packets == QUEUE_MAX || copy->size <= 0 ||
            (size_t)copy->size > PACKET_BYTES_MAX - f->packet_bytes ||
            !picture_identity(&f->enhancement_order, copy, &f->packet_order[f->num_packets])) {
            av_packet_free(&copy);
            goto fail;
        }
        /* The native HEVC parser validates the actual EL headers before any
         * hardware submission; reject configuration/source geometry mismatch. */
        if (f->qsv && (f->enhancement_order.parser->width != f->decoder->width ||
                       f->enhancement_order.parser->height != f->decoder->height)) {
            av_packet_free(&copy);
            goto fail;
        }
        if (f->synchronizing) {
            const AVCodecParserContext *bp = f->base_order.parser;
            const AVCodecParserContext *ep = f->enhancement_order.parser;
            bool common_key = bp->key_frame == 1 && ep->key_frame == 1 &&
                              bp->output_picture_number == ep->output_picture_number;
            /* A non-reordered BL gives the IDR packet an unambiguous display
             * time. Never use this shortcut for a BL with reordered pictures. */
            bool el_idr = ep->key_frame == 1 && ep->output_picture_number == 0 &&
                          f->base_order.context->has_b_frames == 0;
            bool bootstrap = !f->qsv || f->qsv_configuration_present || f->qsv_inband_headers == 7;
            if ((!common_key && !el_idr) || !bootstrap) {
                av_packet_free(&copy);
                f->num_times = 0;
                if (++f->preroll_packets > 1024)
                    goto fail;
                continue;
            }
            f->enhancement_order.offset = base_identity - ep->output_picture_number;
            f->enhancement_order.maximum = base_identity;
            f->packet_order[f->num_packets] = base_identity;
            f->anchor_pts = packet->pts;
            f->synchronizing = false;
        }
        if (f->qsv) {
            const AVCodecParserContext *ep = f->enhancement_order.parser;
            const AVCodecContext *ec = f->enhancement_order.context;
            if (ec->chroma_sample_location == AVCHROMA_LOC_UNSPECIFIED) {
                av_packet_free(&copy);
                goto fail;
            }
            f->packet_properties[f->num_packets] = (struct dvbridge_qsv_properties){
                .width=ep->width, .height=ep->height, .format=ep->format,
                .chroma_location=ec->chroma_sample_location, .color_range=ec->color_range,
                .color_primaries=ec->color_primaries, .color_trc=ec->color_trc,
                .colorspace=ec->colorspace, .sar_num=ec->sample_aspect_ratio.num,
                .sar_den=ec->sample_aspect_ratio.den};
        }
        f->packet_bytes += copy->size;
        f->packets[f->num_packets++] = copy;
    }
fail:
    f->failed = true;
    return false;
}

bool dvbridge_fel_drain(struct dvbridge_fel *f)
{
    if (!f)
        return false;
    if (f->synchronizing) {
        f->failed = true;
        return false; /* EOF cannot supply the missing random-access picture. */
    }
    f->draining = true;
    return pump(f);
}

int dvbridge_fel_take(struct dvbridge_fel *f, int64_t pts, AVFrame **frame)
{
    if (!f || !frame || *frame || pts == AV_NOPTS_VALUE || !pump(f))
        return -1;
    if (f->synchronizing || (f->anchor_pts != AV_NOPTS_VALUE && pts < f->anchor_pts))
        return 2; /* Preroll before a recoverable EL picture, not a substitute. */
    for (unsigned i = 0; i < f->num_frames;) {
        AVFrame *candidate = f->frames[i];
        if (candidate->pts > pts) {
            ++i;
            continue;
        }
        --f->num_frames;
        memmove(f->frames + i, f->frames + i + 1,
                (f->num_frames - i) * sizeof(*f->frames));
        if (candidate->pts == pts) {
            uint64_t sequence = 0;
            if (f->paired_frames == UINT64_MAX ||
                (f->qsv && dvbridge_fel_qsv_frame_route(candidate, &sequence) != 1)) {
                av_frame_free(&candidate);
                f->failed = true;
                return -1;
            }
            ++f->paired_frames;
            *frame = candidate;
            return 1;
        }
        av_frame_free(&candidate);
    }
    /* A later decoded EL frame does not prove the requested one is missing.
     * Keep bounded lookahead and never substitute a neighbouring surface. */
    return f->eof || f->num_frames == QUEUE_MAX ? -1 : 0;
}

bool dvbridge_fel_failed(const struct dvbridge_fel *f)
{
    return !f || f->failed;
}

bool dvbridge_fel_exhausted(const struct dvbridge_fel *f)
{
    return f && !f->failed && f->eof && !f->num_frames && !f->num_packets;
}

bool dvbridge_fel_qsv_selected(const struct dvbridge_fel *f)
{
    return f && f->qsv;
}

uint64_t dvbridge_fel_qsv_mapped_frames(const struct dvbridge_fel *f)
{
    return f ? f->qsv_mapped_frames : 0;
}

uint64_t dvbridge_fel_paired_frames(const struct dvbridge_fel *f)
{
    return f ? f->paired_frames : 0;
}

int dvbridge_fel_qsv_frame_route(const AVFrame *frame, uint64_t *sequence)
{
    if (!frame || !sequence)
        return -1;
    *sequence = 0;
    const AVDictionaryEntry *route = av_dict_get(frame->metadata, "dvbridge.el.qsv", NULL, 0);
    const AVDictionaryEntry *serial = av_dict_get(frame->metadata, "dvbridge.el.qsv_map_sequence", NULL, 0);
    if (!route && !serial)
        return 0;
    if (!route || !serial || strcmp(route->value, "1") || !serial->value[0] ||
        serial->value[0] == '0')
        return -1;
    uint64_t value = 0;
    for (const char *p = serial->value; *p; ++p) {
        if (*p < '0' || *p > '9' || value > (INT64_MAX - (uint64_t)(*p - '0')) / 10)
            return -1;
        value = value * 10 + (*p - '0');
    }
    *sequence = value;
    return 1;
}
