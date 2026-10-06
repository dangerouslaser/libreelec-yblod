/* SPDX-License-Identifier: GPL-3.0-or-later */
/* CPU-only contract test: real AVFrame/refcounting, mocked decoder/hw map.
 * Does not qualify hardware decoding, token propagation or direct mapping. */
#define avcodec_receive_frame test_receive
#define av_hwframe_ctx_create_derived test_derive
#define av_hwframe_map test_map
#define av_packet_free test_packet_free
#ifndef DVBRIDGE_FEL_SOURCE
#define DVBRIDGE_FEL_SOURCE "dvbridge_fel.c"
#endif
#include DVBRIDGE_FEL_SOURCE
#include <libavutil/mem.h>
#include <assert.h>
#include <stdio.h>
static AVFrame *pending;
static int terminal = AVERROR(EAGAIN), fail_map, freed;
void test_packet_free(AVPacket **packet)
{
    (void)packet;
    assert(!"receive-only fixture must not own packets");
}
static void owner_free(void *opaque, uint8_t *data)
{
    (void)opaque;
    ++freed;
    av_free(data);
}
int test_receive(AVCodecContext *ctx, AVFrame *frame)
{
    (void)ctx;
    if (!pending)
        return terminal;
    av_frame_move_ref(frame, pending);
    av_frame_free(&pending);
    return 0;
}
int test_derive(AVBufferRef **out, enum AVPixelFormat format, AVBufferRef *device,
                AVBufferRef *source, int flags)
{
    assert(format == AV_PIX_FMT_VAAPI && source && device);
    assert(flags == (AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT));
    *out = av_buffer_allocz(sizeof(AVHWFramesContext));
    if (!*out)
        return AVERROR(ENOMEM);
    AVHWFramesContext *ctx = (void *)(*out)->data;
    ctx->format = format;
    ctx->device_ctx = (void *)device->data;
    return 0;
}
int test_map(AVFrame *dst, const AVFrame *src, int flags)
{
    assert(dst->format == AV_PIX_FMT_VAAPI && dst->hw_frames_ctx);
    assert(flags == (AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT));
    if (fail_map)
        return AVERROR(ENOSYS);
    dst->buf[0] = av_buffer_ref(src->buf[0]);
    dst->width = src->width;
    dst->height = src->height;
    dst->data[3] = src->data[3];
    return dst->buf[0] ? 0 : AVERROR(ENOMEM);
}
static void queue(int64_t token)
{
    assert(!pending);
    pending = av_frame_alloc();
    assert(pending);
    pending->format = AV_PIX_FMT_QSV;
    pending->width = 1920;
    pending->height = 1088;
    pending->crop_bottom = 8;
    pending->pts = token;
    pending->best_effort_timestamp = token;
    pending->pkt_dts = token;
    pending->duration = 1;
    pending->buf[0] = av_buffer_create(av_malloc(8), 8, owner_free, NULL, 0);
    pending->hw_frames_ctx = av_buffer_allocz(sizeof(AVHWFramesContext));
    assert(pending->buf[0] && pending->hw_frames_ctx);
}
int main(void)
{
    struct dvbridge_fel f = {.qsv = true, .source_time_base = {1, 1000000}};
    f.source_device = av_buffer_allocz(sizeof(AVHWDeviceContext));
    assert(f.source_device);
    ((AVHWDeviceContext *)f.source_device->data)->type = AV_HWDEVICE_TYPE_VAAPI;
    int64_t token;
    assert(dvbridge_qsv_token_peek(&f.tokens, 1234567890123, &token));
    assert(dvbridge_qsv_token_commit(&f.tokens, token, 1234567890123, 41708));
    queue(token);
    assert(receive_frames(&f));
    assert(f.num_frames == 1 && f.qsv_mapped_frames == 1 && f.tokens.count == 0);
    AVFrame *held = f.frames[0];
    assert(held->format == AV_PIX_FMT_VAAPI);
    assert(held->pts == 1234567890123 && held->best_effort_timestamp == held->pts);
    assert(held->pkt_dts == AV_NOPTS_VALUE && held->duration == 41708);
    assert(held->time_base.num == 1 && held->time_base.den == 1000000);
    assert(held->width == 1920 && held->height == 1088 && held->crop_bottom == 8);
    assert(freed == 0); /* mapping owns source after receive's frame was freed */
    AVFrame *consumer = av_frame_clone(held);
    assert(consumer);
    clear_queues(&f);
    assert(freed == 0 && consumer->hw_frames_ctx);
    av_frame_free(&consumer);
    assert(freed == 1);
    /* Unknown/duplicate timestamp never maps a neighbouring frame. */
    queue(token);
    assert(!receive_frames(&f) && f.num_frames == 0 && f.qsv_mapped_frames == 1);
    assert(freed == 2);
    assert(dvbridge_qsv_token_peek(&f.tokens, 55, &token));
    assert(dvbridge_qsv_token_commit(&f.tokens, token, 55, 2));
    queue(token);
    fail_map = 1;
    assert(!receive_frames(&f) && f.num_frames == 0 && f.qsv_mapped_frames == 1);
    assert(freed == 3);
    clear_queues(&f);
    assert(dvbridge_qsv_token_peek(&f.tokens, 77, &token));
    assert(dvbridge_qsv_token_commit(&f.tokens, token, 77, 2));
    terminal = AVERROR_EOF;
    assert(!receive_frames(&f) && !f.eof); /* unresolved submitted surface */
    clear_queues(&f);
    assert(receive_frames(&f) && f.eof);
    av_buffer_unref(&f.source_device);
    puts("QSV receive contract: PASS (refs, crop, timestamps, mapping failure, unknown output, EOF)");
    return 0;
}
