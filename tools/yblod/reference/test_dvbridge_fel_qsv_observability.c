/* SPDX-License-Identifier: GPL-3.0-or-later */
/* CPU-only contract test: real AVFrame/refcounting, mocked decoder/hw map.
 * Does not qualify hardware decoding, token propagation or direct mapping. */
#define avcodec_receive_frame test_receive
#define avcodec_send_packet test_send
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
int test_send(AVCodecContext *context, const AVPacket *packet)
{
    (void)context;
    (void)packet;
    assert(!"receive/pair fixture must not submit packets");
    return AVERROR(EINVAL);
}
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
    /* Untrusted input markers must not impersonate a decoder route. */
    assert(av_dict_set(&pending->metadata, "dvbridge.el.qsv", "1", 0) == 0);
    assert(av_dict_set(&pending->metadata, "dvbridge.el.qsv_map_sequence", "999", 0) == 0);
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
    uint64_t sequence = 0;
    assert(dvbridge_fel_qsv_frame_route(held, &sequence) == 1 && sequence == 1);
    AVFrame *paired = NULL;
    assert(dvbridge_fel_take(&f, held->pts, &paired) == 1 && paired == held);
    assert(dvbridge_fel_paired_frames(&f) == 1 && f.num_frames == 0);
    f.frames[f.num_frames++] = paired;
    assert(held->format == AV_PIX_FMT_VAAPI);
    assert(held->pts == 1234567890123 && held->best_effort_timestamp == held->pts);
    assert(held->pkt_dts == AV_NOPTS_VALUE && held->duration == 41708);
    assert(held->time_base.num == 1 && held->time_base.den == 1000000);
    assert(held->width == 1920 && held->height == 1088 && held->crop_bottom == 8);
    assert(freed == 0); /* mapping owns source after receive's frame was freed */
    AVFrame *consumer = av_frame_clone(held);
    assert(consumer);
    clear_queues(&f);
    assert(dvbridge_fel_paired_frames(&f) == 1 && dvbridge_fel_qsv_mapped_frames(&f) == 1);
    assert(dvbridge_fel_qsv_frame_route(consumer, &sequence) == 1 && sequence == 1);
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
    terminal = AVERROR(EAGAIN);
    f.qsv = false;
    queue(123);
    pending->format = AV_PIX_FMT_VAAPI;
    assert(receive_frames(&f) && f.num_frames == 1);
    assert(dvbridge_fel_qsv_frame_route(f.frames[0], &sequence) == 0 && sequence == 0);
    clear_queues(&f);
    AVFrame *marker = av_frame_alloc();
    assert(marker);
    assert(dvbridge_fel_qsv_frame_route(marker, &sequence) == 0);
    assert(av_dict_set(&marker->metadata, "dvbridge.el.qsv", "1", 0) == 0);
    assert(dvbridge_fel_qsv_frame_route(marker, &sequence) == -1);
    const char *invalid[] = {"", "0", "01", "-1", "+1", " 1", "1 ", "18446744073709551616", "9223372036854775808", "1x"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); ++i) {
        assert(av_dict_set(&marker->metadata, "dvbridge.el.qsv_map_sequence", invalid[i], 0) == 0);
        assert(dvbridge_fel_qsv_frame_route(marker, &sequence) == -1);
    }
    assert(av_dict_set(&marker->metadata, "dvbridge.el.qsv_map_sequence", "9223372036854775807", 0) == 0);
    assert(dvbridge_fel_qsv_frame_route(marker, &sequence) == 1 && sequence == INT64_MAX);
    assert(av_dict_set(&marker->metadata, "dvbridge.el.qsv", "0", 0) == 0);
    assert(dvbridge_fel_qsv_frame_route(marker, &sequence) == -1);
    av_frame_free(&marker);
    av_buffer_unref(&f.source_device);
    puts("QSV observability contract: PASS (actual-map marker, spoof cleanup, exact pairing, ref copies, strict marker parsing, counters)");
    return 0;
}
