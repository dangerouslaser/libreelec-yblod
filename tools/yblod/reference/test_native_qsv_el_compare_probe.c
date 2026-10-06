/* SPDX-License-Identifier: GPL-3.0-or-later */
/* CPU-only contracts; includes the real diagnostic helpers, no GPU/media. */
#define main diagnostic_main_not_run
#include "native_qsv_el_compare_probe.c"
#undef main
#include <assert.h>

int main(void)
{
    AVFrame *a = av_frame_alloc(), *b = av_frame_alloc();
    assert(a && b);
    a->format = b->format = AV_PIX_FMT_P010;
    a->width = b->width = 1920;
    a->height = 1080;
    b->height = 1088;
    b->crop_bottom = 8;
    assert(active_geometry(a) && active_geometry(b));
    assert(properties(a, b)); /* padding representation is not display geometry */
    assert(av_frame_get_buffer(a, 32) == 0 && av_frame_get_buffer(b, 32) == 0);
    assert(valid_buffers(a) && valid_buffers(b));
    memset(a->buf[0]->data, 0, a->buf[0]->size);
    memset(b->buf[0]->data, 0, b->buf[0]->size);
    memset(b->data[0] + 1080 * b->linesize[0], 255, 8 * b->linesize[0]);
    memset(b->data[1] + 540 * b->linesize[1], 255, 4 * b->linesize[1]);
    for (unsigned plane = 0; plane < 3; ++plane) {
        struct plane_comparison result = compare_plane(a, b, plane);
        assert(!result.differences && !result.max_delta && !result.low_bits);
    }
    ((uint16_t *)b->data[1])[1] = 64;
    assert(compare_plane(a, b, 1).differences == 0);
    assert(compare_plane(a, b, 2).differences == 1);
    assert(compare_plane(a, b, 2).max_delta == 1);
    ((uint16_t *)b->data[1])[1] = 1;
    assert(compare_plane(a, b, 2).differences == 1);
    assert(compare_plane(a, b, 2).max_delta == 0);
    assert(compare_plane(a, b, 2).low_bits == 1);
    ((uint16_t *)b->data[1])[1] = 0;
    b->crop_bottom = 7;
    assert(!active_geometry(b));
    b->crop_bottom = SIZE_MAX;
    assert(!active_geometry(b));
    b->crop_bottom = 8;
    int stride = b->linesize[0];
    b->linesize[0] = 100;
    assert(!valid_buffers(b));
    b->linesize[0] = -stride;
    assert(!valid_buffers(b));
    b->linesize[0] = stride;
    uint8_t *data = b->data[0];
    b->data[0] += b->buf[0]->size - 2;
    assert(!valid_buffers(b));
    b->data[0] = data;
    b->duration = 1;
    assert(!properties(a, b));
    b->duration = 0;
    b->best_effort_timestamp = 123;
    assert(!properties(a, b));
    b->best_effort_timestamp = a->best_effort_timestamp;
    b->time_base = (AVRational){1, 1000000};
    assert(!properties(a, b));
    a->time_base = b->time_base;
    b->chroma_location = AVCHROMA_LOC_CENTER;
    assert(!properties(a, b));
    b->chroma_location = a->chroma_location;
    b->color_trc = AVCOL_TRC_SMPTE2084;
    assert(!properties(a, b));
    b->color_trc = a->color_trc;
    assert(properties(a, b));
    struct stat x = {.st_mode = S_IFREG, .st_dev = 1, .st_ino = 2, .st_size = 3};
    struct stat y = x;
    assert(same_source(&x, &y));
    y.st_ino++;
    assert(!same_source(&x, &y));
    y = x; y.st_mtim.tv_nsec = 1;
    assert(!same_source(&x, &y));
    y = x; y.st_size++;
    assert(!same_source(&x, &y));
    y = x; y.st_dev++;
    assert(!same_source(&x, &y));
    int64_t converted;
    assert(kodi_timestamp(90001, (AVRational){1, 90000}, 1000000, &converted));
    assert(converted == 11);
    assert(kodi_timestamp(AV_NOPTS_VALUE, (AVRational){1, 1}, 0, &converted));
    assert(converted == AV_NOPTS_VALUE);
    assert(!kodi_timestamp(1, (AVRational){1, 0}, 0, &converted));
    assert(!kodi_timestamp(INT64_MAX, (AVRational){INT_MAX, 1}, 0, &converted));
    int target = 0;
    const int takes[] = {2, 0, 1};
    for (unsigned step = 0; step < 3; ++step) {
        int action = take_action(takes[step]);
        assert(action >= 0 && target == 0);
        if (action == 1) ++target;
    }
    assert(target == 1 && take_action(-1) == -1 && take_action(3) == -1);
    const char *avutil = getenv("EXPECTED_CPU_AVUTIL");
    assert(avutil && setenv("EXPECTED_CPU_MAP", avutil, 1) == 0);
    assert(loaded_exact("EXPECTED_CPU_MAP", "libavutil.so."));
    assert(setenv("EXPECTED_CPU_MAP", "/etc/passwd", 1) == 0);
    assert(!loaded_exact("EXPECTED_CPU_MAP", "libavutil.so."));
    assert(setenv("EXPECTED_CPU_MAP", "/not-present-sdk-library", 1) == 0);
    assert(!loaded_exact("EXPECTED_CPU_MAP", "libavutil.so."));
    assert(!sdk_runtime_loaded()); /* No GPU implementation or driver loaded. */
    record_frame(a);
    failure_stage = "cpu_fixture";
    failure_route = 0;
    assert(diagnostic_failure(0) == 0); /* Formatter checked by host JSON parser. */
    av_frame_free(&a);
    av_frame_free(&b);
    puts("CPU-only geometry/bounds/properties/source-stat/Kodi-timestamp contracts PASS");
    return 0;
}
