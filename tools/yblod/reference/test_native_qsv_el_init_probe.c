/* SPDX-License-Identifier: GPL-3.0-or-later */
#define YB_INIT_ENTRYPOINT unused_init_diagnostic_main
#include "native_qsv_el_init_probe.c"
#include <assert.h>

static enum AVPixelFormat dummy_format(AVCodecContext *ctx, const enum AVPixelFormat *formats)
{
    (void)ctx;
    return formats[0];
}

int main(void)
{
    counts[1].accepted_packets = 0;
    record_capture_submission(0);
    assert(counts[1].accepted_packets == 0);
    record_capture_submission(1);
    assert(counts[1].accepted_packets == 1);
    const AVCodec *codec = avcodec_find_decoder_by_name("hevc_qsv");
    assert(codec);
    AVCodecContext *ctx = avcodec_alloc_context3(codec);
    AVPacket *packet = av_packet_alloc();
    assert(ctx && packet && av_new_packet(packet, 8) == 0);
    for (int i = 0; i < 8; ++i) packet->data[i] = i;
    packet->pts = 1; packet->duration = 0;
    ctx->width = 1920; ctx->height = 1088;
    ctx->pkt_timebase = (AVRational){1,90000};
    ctx->thread_count = 1; ctx->get_format = dummy_format;
    ctx->flags = AV_CODEC_FLAG_COPY_OPAQUE;
    capture_active = 1;
    assert(__wrap_avcodec_send_packet(ctx, packet) == AVERROR_EXTERNAL);
    assert(first_au && first_parameters && first_au->pts == 1 &&
        first_timebase.num == 1 && first_timebase.den == 90000 &&
        first_threads == 1 && first_get_format == dummy_format && first_flags == ctx->flags);
    assert(first_parameters->width == ctx->width && first_parameters->height == ctx->height);
    assert(!memcmp(first_au->data, packet->data, packet->size));
    av_packet_free(&packet);
    avcodec_free_context(&ctx);
    /* Captured parameters/buffer own their lifetime after helper/ctx release. */
    assert(first_au->size == 8 && first_au->data[7] == 7 && first_parameters->width == 1920);
    av_packet_free(&first_au); avcodec_parameters_free(&first_parameters);
    puts("CPU-only actual-send interception/capture ownership contracts PASS; no decode executed");
    return 0;
}
