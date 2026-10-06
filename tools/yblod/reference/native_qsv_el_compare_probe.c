/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Diagnostic only: downloads EL samples to compare two real helper routes.
 * The product helper still maps QSV directly to VAAPI without a CPU download.
 * No media bytes or content hashes are written or reported. */
#include "dvbridge_fel.h"
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/pixdesc.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum { FRAME_COUNT = 3, PACKET_LIMIT = 4096 };

static int active_geometry(const AVFrame *f)
{
    return f && f->width > 0 && f->width <= 2048 && f->height > 0 &&
        f->height <= 1152 && !(f->width & 1) && !(f->height & 1) &&
        f->crop_left < (size_t)f->width && f->crop_right < (size_t)f->width &&
        f->crop_top < (size_t)f->height && f->crop_bottom < (size_t)f->height &&
        !((f->crop_left | f->crop_right | f->crop_top | f->crop_bottom) & 1) &&
        (size_t)f->width == f->crop_left + f->crop_right + 1920 &&
        (size_t)f->height == f->crop_top + f->crop_bottom + 1080;
}

static int valid_buffers(AVFrame *f)
{
    if (!active_geometry(f) || f->format != AV_PIX_FMT_P010)
        return 0;
    for (unsigned p = 0; p < 2; ++p) {
        AVBufferRef *buffer = av_frame_get_plane_buffer(f, p);
        size_t rows = (size_t)f->height >> p;
        size_t row_bytes = (size_t)f->width * 2;
        if (!buffer || !f->data[p] || f->linesize[p] <= 0 ||
            (size_t)f->linesize[p] < row_bytes)
            return 0;
        uintptr_t start = (uintptr_t)buffer->data, data = (uintptr_t)f->data[p];
        size_t span = (rows - 1) * (size_t)f->linesize[p] + row_bytes;
        if (data < start || data - start > buffer->size ||
            span > buffer->size - (data - start))
            return 0;
    }
    return 1;
}

static int same_source(const struct stat *a, const struct stat *b)
{
    return S_ISREG(a->st_mode) && S_ISREG(b->st_mode) &&
        a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_size == b->st_size &&
        a->st_mtim.tv_sec == b->st_mtim.tv_sec && a->st_mtim.tv_nsec == b->st_mtim.tv_nsec;
}

static int loaded_exact(const char *environment, const char *family)
{
    const char *expected = getenv(environment);
    if (!expected || expected[0] != '/')
        return 0;
    char *canonical = realpath(expected, NULL);
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!canonical || !maps) {
        free(canonical);
        if (maps) fclose(maps);
        return 0;
    }
    char line[8192];
    int found = 0, wrong = 0;
    while (fgets(line, sizeof(line), maps)) {
        char *path = strchr(line, '/');
        if (!path)
            continue;
        path[strcspn(path, "\n")] = 0;
        const char *basename = strrchr(path, '/');
        if (!basename || strncmp(basename + 1, family, strlen(family)))
            continue;
        if (!strcmp(path, canonical))
            found = 1;
        else
            wrong = 1;
    }
    int error = ferror(maps);
    fclose(maps);
    free(canonical);
    return found && !wrong && !error;
}

static int sdk_runtime_loaded(void)
{
    return loaded_exact("EXPECTED_QSV_LIBVPL", "libvpl.so.") &&
        loaded_exact("EXPECTED_QSV_IMPLEMENTATION", "libmfx-gen.so.") &&
        loaded_exact("EXPECTED_QSV_VA_DRIVER", "iHD_drv_video.so");
}

static int integer(const char *text, int64_t *value)
{
    char *end;
    errno = 0;
    *value = strtoll(text, &end, 10);
    return !errno && *text && !*end && *value >= 0;
}

/* Ordinary MKV Kodi demux/AddData contract, including truncation. This is not
 * rational nearest rounding; TS/menu paths are deliberately unsupported. */
static int kodi_timestamp(int64_t raw, AVRational tb, int64_t start, int64_t *out)
{
    if (raw == AV_NOPTS_VALUE) {
        *out = raw;
        return 1;
    }
    if (tb.num <= 0 || tb.den <= 0)
        return 0;
    double timestamp = (double)raw * tb.num / tb.den;
    double starttime = start == AV_NOPTS_VALUE ? 0 : (double)start / AV_TIME_BASE;
    if (timestamp > starttime)
        timestamp -= starttime;
    else if (timestamp + 0.5 > starttime)
        timestamp = 0;
    double packet_pts = timestamp * 1000000.0;
    double submitted = packet_pts / 1000000.0 * AV_TIME_BASE;
    if (!isfinite(submitted) || submitted <= (double)INT64_MIN || submitted >= (double)INT64_MAX)
        return 0;
    *out = (int64_t)submitted;
    return 1;
}

static int download(AVFrame *hardware, AVBufferRef *device, int qsv,
                    int64_t pts, AVFrame **result)
{
    uint64_t sequence;
    if (!hardware || hardware->format != AV_PIX_FMT_VAAPI ||
        hardware->pts != pts || !hardware->hw_frames_ctx ||
        dvbridge_fel_qsv_frame_route(hardware, &sequence) != qsv)
        return 0;
    AVHWFramesContext *frames = (void *)hardware->hw_frames_ctx->data;
    if (frames->device_ctx != (AVHWDeviceContext *)device->data ||
        frames->sw_format != AV_PIX_FMT_P010 || !active_geometry(hardware))
        return 0;
    AVFrame *software = av_frame_alloc();
    if (!software || av_hwframe_transfer_data(software, hardware, 0) < 0 ||
        av_frame_copy_props(software, hardware) < 0 || software->width <= 0 ||
        software->height <= 0 || software->width > 2048 || software->height > 1152 ||
        (size_t)software->width < hardware->crop_left + 1920 ||
        (size_t)software->height < hardware->crop_top + 1080) {
        av_frame_free(&software);
        return 0;
    }
    /* VAAPI readback can expose the pool's coded bottom padding even when the
     * hardware AVFrame already describes visible height. Preserve the active
     * origin and derive only right/bottom padding from the destination extent. */
    software->crop_right = (size_t)software->width - software->crop_left - 1920;
    software->crop_bottom = (size_t)software->height - software->crop_top - 1080;
    if (!valid_buffers(software)) {
        av_frame_free(&software);
        return 0;
    }
    *result = software;
    return 1;
}

static int route(const char *path, AVBufferRef *device, int qsv, int64_t seek_us,
                 const int64_t pts[FRAME_COUNT], AVFrame *output[FRAME_COUNT],
                 uint64_t *mapped)
{
    AVFormatContext *input = NULL;
    struct dvbridge_fel *helper = NULL;
    AVPacket *packet = av_packet_alloc();
    int ok = 0, stream, next = 0;
    if (!packet || setenv("DVBRIDGE_FEL_QSV", qsv ? "1" : "0", 1) ||
        avformat_open_input(&input, path, NULL, NULL) < 0 ||
        avformat_find_stream_info(input, NULL) < 0)
        goto done;
    stream = av_find_best_stream(input, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
    if (stream < 0 || !input->iformat ||
        strcmp(input->iformat->name, "matroska,webm") ||
        input->streams[stream]->codecpar->codec_id != AV_CODEC_ID_HEVC ||
        avformat_seek_file(input, -1, INT64_MIN, seek_us, seek_us, 0) < 0)
        goto done;
    helper = dvbridge_fel_create(input->streams[stream]->codecpar,
                                AV_TIME_BASE_Q);
    if (!helper || dvbridge_fel_qsv_selected(helper) != !!qsv ||
        !dvbridge_fel_device(helper, device))
        goto done;
    for (unsigned count = 0; count < PACKET_LIMIT && next < FRAME_COUNT; ++count) {
        int read = av_read_frame(input, packet);
        if (read < 0) {
            if (read != AVERROR_EOF || !dvbridge_fel_drain(helper))
                goto done;
        } else {
            if (packet->stream_index != stream) {
                av_packet_unref(packet);
                continue;
            }
            if (!kodi_timestamp(packet->pts, input->streams[stream]->time_base,
                                input->start_time, &packet->pts) ||
                !kodi_timestamp(packet->dts, input->streams[stream]->time_base,
                                input->start_time, &packet->dts))
                goto done;
            packet->duration = 0; /* Actual Kodi AddData does not set duration. */
            packet->time_base = AV_TIME_BASE_Q;
            if (!dvbridge_fel_submit(helper, packet))
                goto done;
            av_packet_unref(packet);
        }
        while (next < FRAME_COUNT) {
            AVFrame *frame = NULL;
            int take = dvbridge_fel_take(helper, pts[next], &frame);
            if (take < 0 || take == 2)
                goto done;
            if (!take)
                break;
            int valid = download(frame, device, qsv, pts[next], &output[next]);
            av_frame_free(&frame);
            if (!valid)
                goto done;
            ++next;
        }
        if (read == AVERROR_EOF && next != FRAME_COUNT)
            goto done;
    }
    *mapped = dvbridge_fel_qsv_mapped_frames(helper);
    ok = next == FRAME_COUNT && (!qsv || sdk_runtime_loaded()) &&
         dvbridge_fel_paired_frames(helper) == FRAME_COUNT &&
         (qsv ? *mapped >= FRAME_COUNT : *mapped == 0);
done:
    dvbridge_fel_destroy(helper);
    av_packet_free(&packet);
    avformat_close_input(&input);
    return ok;
}

static int properties(const AVFrame *a, const AVFrame *b)
{
    return a->pts == b->pts && a->best_effort_timestamp == b->best_effort_timestamp &&
        a->duration == b->duration && a->time_base.num == b->time_base.num &&
        a->time_base.den == b->time_base.den && a->format == b->format &&
        active_geometry(a) && active_geometry(b) && a->chroma_location == b->chroma_location &&
        a->color_range == b->color_range && a->color_primaries == b->color_primaries &&
        a->color_trc == b->color_trc && a->colorspace == b->colorspace &&
        av_cmp_q(a->sample_aspect_ratio, b->sample_aspect_ratio) == 0;
}

static void scalar_properties(const AVFrame *a, const AVFrame *b)
{
    int timestamps = a->pts == b->pts && a->best_effort_timestamp == b->best_effort_timestamp &&
        a->duration == b->duration && a->time_base.num == b->time_base.num && a->time_base.den == b->time_base.den;
    int colours = a->color_range == b->color_range && a->color_primaries == b->color_primaries &&
        a->color_trc == b->color_trc && a->colorspace == b->colorspace;
    printf("\"active_geometry_equal\":%s,\"chroma_location_equal\":%s,\"colour_properties_equal\":%s,\"original_timestamps_equal\":%s,",
        active_geometry(a) && active_geometry(b) ? "true" : "false",
        a->chroma_location == b->chroma_location ? "true" : "false", colours ? "true" : "false",
        timestamps ? "true" : "false");
    const AVFrame *frames[] = {a, b};
    const char *names[] = {"before", "after"};
    for (unsigned i = 0; i < 2; ++i) {
        const AVFrame *f = frames[i];
        printf("\"%s\":{\"pts_microseconds\":%" PRId64 ",\"best_effort_timestamp\":%" PRId64 ",\"duration\":%" PRId64 ",\"time_base\":[%d,%d],\"coded_width\":%d,\"coded_height\":%d,\"crop\":[%zu,%zu,%zu,%zu],\"chroma_location\":%d,\"color_range\":%d,\"color_primaries\":%d,\"color_trc\":%d,\"colorspace\":%d},",
            names[i], f->pts, f->best_effort_timestamp, f->duration, f->time_base.num, f->time_base.den,
            f->width, f->height, f->crop_left, f->crop_top, f->crop_right, f->crop_bottom,
            f->chroma_location, f->color_range, f->color_primaries, f->color_trc, f->colorspace);
    }
}

struct plane_comparison { uint64_t differences; unsigned max_delta, low_bits; };

static struct plane_comparison compare_plane(const AVFrame *a, const AVFrame *b, unsigned plane)
{
    struct plane_comparison result = {0};
    unsigned width = plane ? 960 : 1920, height = plane ? 540 : 1080;
    for (unsigned y = 0; y < height; ++y) {
        const uint16_t *aa = (const void *)(a->data[!!plane] +
            (y + (a->crop_top >> !!plane)) * a->linesize[!!plane] + a->crop_left * 2);
        const uint16_t *bb = (const void *)(b->data[!!plane] +
            (y + (b->crop_top >> !!plane)) * b->linesize[!!plane] + b->crop_left * 2);
        for (unsigned x = 0; x < width; ++x) {
            unsigned offset = plane ? 2 * x + plane - 1 : x;
            unsigned av = aa[offset], bv = bb[offset];
            result.low_bits |= (av | bv) & 63;
            result.differences += av != bv;
            unsigned ac = av >> 6, bc = bv >> 6;
            unsigned delta = ac > bc ? ac - bc : bc - ac;
            if (delta > result.max_delta)
                result.max_delta = delta;
        }
    }
    return result;
}

int main(int argc, char **argv)
{
    /* File/render node stay private; requested PTS match Kodi capture microseconds. */
    int64_t seek_us, pts[FRAME_COUNT];
    if (argc != 7 || !integer(argv[3], &seek_us))
        return 2;
    for (int i = 0; i < FRAME_COUNT; ++i)
        if (!integer(argv[i + 4], &pts[i]) || (i && pts[i] <= pts[i - 1]))
            return 2;
    /* The bounded launcher redirects all decoder diagnostics to a private file. */
    av_log_set_level(AV_LOG_ERROR);
    struct stat initial, middle, final;
    if (stat(argv[1], &initial) || !S_ISREG(initial.st_mode))
        return 2;
    AVBufferRef *device = NULL;
    AVFrame *reference[FRAME_COUNT] = {0}, *candidate[FRAME_COUNT] = {0};
    uint64_t mapped[2] = {0};
    int ok = av_hwdevice_ctx_create(&device, AV_HWDEVICE_TYPE_VAAPI, argv[2], NULL, 0) >= 0 &&
        route(argv[1], device, 0, seek_us, pts, reference, &mapped[0]) &&
        !stat(argv[1], &middle) && same_source(&initial, &middle) &&
        route(argv[1], device, 1, seek_us, pts, candidate, &mapped[1]) &&
        !stat(argv[1], &final) && same_source(&initial, &final);
    if (ok) {
        printf("{\"scope\":\"actual EL helper routes; diagnostic-only CPU readback, not Kodi output/performance\",\"input_stat_identity_unchanged\":true,\"expected_sdk_libvpl_loaded\":true,\"expected_sdk_implementation_loaded\":true,\"expected_sdk_va_driver_loaded\":true,\"frames\":[");
        for (int i = 0; i < FRAME_COUNT; ++i) {
            int equal_props = properties(reference[i], candidate[i]);
            if (!equal_props)
                ok = 0;
            printf("%s{\"requested_pts_microseconds\":%" PRId64 ",\"format\":\"P010\",\"code_bit_depth\":10,\"active_width\":1920,\"active_height\":1080,\"properties_equal\":%s,",
                   i ? "," : "", pts[i], equal_props ? "true" : "false");
            scalar_properties(reference[i], candidate[i]);
            printf("\"planes\":[");
            for (int plane = 0; plane < 3; ++plane) {
                unsigned width = plane ? 960 : 1920, height = plane ? 540 : 1080;
                struct plane_comparison result = compare_plane(reference[i], candidate[i], plane);
                if (result.differences || result.low_bits)
                    ok = 0;
                printf("%s{\"plane\":\"%s\",\"sample_count\":%u,\"differing_samples\":%" PRIu64 ",\"maximum_absolute_sample_codes\":%u,\"p010_low_bits_zero\":%s}",
                       plane ? "," : "", plane == 0 ? "Y" : plane == 1 ? "U" : "V", width * height, result.differences, result.max_delta,
                       result.low_bits ? "false" : "true");
            }
            printf("]}");
        }
        printf("],\"qsv_mapped_frames\":%" PRIu64 ",\"pass\":%s}\n", mapped[1], ok ? "true" : "false");
    }
    for (int i = 0; i < FRAME_COUNT; ++i) {
        av_frame_free(&reference[i]);
        av_frame_free(&candidate[i]);
    }
    av_buffer_unref(&device);
    return ok ? 0 : 1;
}
