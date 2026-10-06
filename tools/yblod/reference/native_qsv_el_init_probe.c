/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Controlled initialization diagnostic, not a replacement DV pipeline.
 * Reuse the real helper's first decoder-bound EL AU, without exporting bytes.
 * Build this file with the actual helper and --wrap=avcodec_send_packet. */
#define main unused_colour_comparison_main
#include "native_qsv_el_compare_probe.c"
#undef main
#include <libavutil/sha.h>

static AVPacket *first_au;
static AVCodecParameters *first_parameters;
static AVRational first_timebase;
static enum AVPixelFormat (*first_get_format)(AVCodecContext *, const enum AVPixelFormat *);
static int first_flags, first_flags2, first_threads, capture_active;
static void record_capture_submission(int accepted)
{
    if (accepted) ++counts[1].accepted_packets;
}
int __real_avcodec_send_packet(AVCodecContext *, const AVPacket *);

int __wrap_avcodec_send_packet(AVCodecContext *context, const AVPacket *packet)
{
    if (capture_active && context && context->codec &&
        !strcmp(context->codec->name, "hevc_qsv") && packet && packet->size > 0) {
        STAGE("capture_actual_helper_decoder_au");
        if (first_au || packet->size > 64 * 1024 * 1024)
            return AVERROR_EXTERNAL;
        first_au = av_packet_clone(packet);
        first_parameters = avcodec_parameters_alloc();
        if (!first_au || !first_parameters ||
            avcodec_parameters_from_context(first_parameters, context) < 0)
            return AVERROR(ENOMEM);
        first_timebase = context->pkt_timebase;
        first_get_format = context->get_format;
        first_flags = context->flags;
        first_flags2 = context->flags2;
        first_threads = context->thread_count;
        return AVERROR_EXTERNAL; /* Intentional diagnostic interception. */
    }
    return __real_avcodec_send_packet(context, packet);
}

static int private_au_identity(void)
{
    const char *path = getenv("PRIVATE_AU_IDENTITY_PATH");
    if (!path || path[0] != '/' || !first_au || !first_parameters)
        return 0;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return 0;
    struct AVSHA *hash = av_sha_alloc();
    uint8_t digest[32];
    char hex[65], text[256];
    int ok = hash && !av_sha_init(hash, 256);
    if (ok) {
        av_sha_update(hash, first_au->data, first_au->size);
        av_sha_final(hash, digest);
        for (unsigned i = 0; i < 32; ++i)
            snprintf(hex + 2 * i, 3, "%02x", digest[i]);
        int size = snprintf(text, sizeof(text), "{\"sha256\":\"%s\",\"pts\":%" PRId64 ",\"time_base\":[%d,%d]}\n",
            hex, first_au->pts, first_timebase.num, first_timebase.den);
        ok = size > 0 && (size_t)size < sizeof(text) && write(fd, text, size) == size;
    }
    av_free(hash);
    close(fd);
    return ok;
}

static int capture_au(const char *file, AVBufferRef *vaapi, int64_t seek)
{
    AVFormatContext *input = NULL;
    struct dvbridge_fel *helper = NULL;
    AVPacket *packet = av_packet_alloc();
    int stream = -1, ok = 0;
    failure_route = 1;
    STAGE("capture_input_open");
    if (!packet || setenv("DVBRIDGE_FEL_QSV", "1", 1) ||
        avformat_open_input(&input, file, NULL, NULL) < 0)
        goto done;
    STAGE("capture_stream_info");
    if (avformat_find_stream_info(input, NULL) < 0)
        goto done;
    stream = av_find_best_stream(input, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
    if (stream < 0 || !input->iformat || strcmp(input->iformat->name, "matroska,webm"))
        goto done;
    for (unsigned i = 0; i < input->nb_streams; ++i)
        if ((int)i != stream) input->streams[i]->discard = AVDISCARD_ALL;
    STAGE("capture_seek");
    if (avformat_seek_file(input, -1, INT64_MIN, seek, seek, 0) < 0)
        goto done;
    STAGE("capture_helper_create");
    helper = dvbridge_fel_create(input->streams[stream]->codecpar, AV_TIME_BASE_Q);
    STAGE("capture_helper_device");
    if (!helper || !dvbridge_fel_device(helper, vaapi))
        goto done;
    capture_active = 1;
    while (!first_au) {
        struct timespec now;
        const char *limit = count_limit(counts[1].demux_reads, counts[1].accepted_packets);
        if (limit) { STAGE(limit); goto done; }
        if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec >= wall_deadline)
            goto done;
        STAGE("capture_read");
        if (av_read_frame(input, packet) < 0)
            goto done;
        ++counts[1].demux_reads;
        if (packet->stream_index != stream) { av_packet_unref(packet); continue; }
        if (!kodi_timestamp(packet->pts, input->streams[stream]->time_base, input->start_time, &packet->pts) ||
            !kodi_timestamp(packet->dts, input->streams[stream]->time_base, input->start_time, &packet->dts))
            goto done;
        packet->duration = 0;
        packet->time_base = AV_TIME_BASE_Q;
        last_video_pts[1] = packet->pts;
        STAGE("capture_helper_submit");
        int accepted = dvbridge_fel_submit(helper, packet);
        av_packet_unref(packet);
        if (!accepted && !first_au) goto done;
        record_capture_submission(accepted);
    }
    ok = first_au && first_parameters && first_get_format && first_threads == 1 && private_au_identity();
done:
    capture_active = 0;
    STAGE("capture_helper_destroy");
    dvbridge_fel_destroy(helper);
    av_packet_free(&packet);
    STAGE("capture_input_close");
    avformat_close_input(&input);
    return ok;
}

#ifndef YB_INIT_ENTRYPOINT
#define YB_INIT_ENTRYPOINT main
#endif
int YB_INIT_ENTRYPOINT(int argc, char **argv)
{
    int64_t seek;
    if (argc != 5 || !integer(argv[3], &seek) ||
        (strcmp(argv[4], "derived36") && strcmp(argv[4], "derived0") && strcmp(argv[4], "direct36")))
        return diagnostic_failure(2);
    if (!open_progress(getenv("PRIVATE_PROGRESS_PATH")))
        return diagnostic_failure(2);
    av_log_set_level(AV_LOG_ERROR);
    struct timespec now;
    struct stat before, after;
    if (clock_gettime(CLOCK_MONOTONIC, &now) || stat(argv[1], &before))
        return diagnostic_failure(2);
    wall_deadline = now.tv_sec + WALL_SECONDS;
    AVBufferRef *vaapi = NULL, *qsv = NULL;
    AVCodecContext *decoder = NULL;
    AVFrame *frame = av_frame_alloc();
    int ok = 0;
    STAGE("capture_vaapi_device");
    if (!frame || av_hwdevice_ctx_create(&vaapi, AV_HWDEVICE_TYPE_VAAPI, argv[2], NULL, 0) < 0 ||
        !capture_au(argv[1], vaapi, seek))
        goto done;
    STAGE("standalone_qsv_device");
    if (!strcmp(argv[4], "direct36")) {
        AVDictionary *options = NULL;
        av_dict_set(&options, "child_device_type", "vaapi", 0);
        av_dict_set(&options, "child_device", argv[2], 0);
        int result = av_hwdevice_ctx_create(&qsv, AV_HWDEVICE_TYPE_QSV, "hw_any", options, 0);
        av_dict_free(&options);
        if (result < 0) goto done;
    } else if (av_hwdevice_ctx_create_derived(&qsv, AV_HWDEVICE_TYPE_QSV, vaapi, 0) < 0)
        goto done;
    STAGE("standalone_codec_create");
    const AVCodec *codec = avcodec_find_decoder_by_name("hevc_qsv");
    if (!codec) goto done;
    decoder = avcodec_alloc_context3(codec);
    if (!decoder || avcodec_parameters_to_context(decoder, first_parameters) < 0)
        goto done;
    decoder->get_format = first_get_format;
    decoder->pkt_timebase = first_timebase;
    decoder->thread_count = first_threads;
    decoder->flags = first_flags; decoder->flags2 = first_flags2;
    decoder->extra_hw_frames = !strcmp(argv[4], "derived0") ? 0 : 36;
    decoder->hw_device_ctx = av_buffer_ref(qsv);
    AVDictionary *options = NULL;
    av_dict_set_int(&options, "async_depth", 1, 0);
    STAGE("standalone_codec_open");
    int opened = avcodec_open2(decoder, decoder->codec, &options);
    int unused = av_dict_count(options);
    av_dict_free(&options);
    if (opened < 0 || unused) goto done;
    STAGE("standalone_first_au_send");
    if (__real_avcodec_send_packet(decoder, first_au) < 0)
        goto done;
    STAGE("standalone_first_frame_receive");
    int received = avcodec_receive_frame(decoder, frame);
    if (received == AVERROR(EAGAIN)) {
        STAGE("standalone_drain_send");
        if (__real_avcodec_send_packet(decoder, NULL) < 0) goto done;
        STAGE("standalone_drain_receive");
        received = avcodec_receive_frame(decoder, frame);
    }
    record_frame(frame);
    STAGE("standalone_runtime_maps");
    ok = !received && frame->format == AV_PIX_FMT_QSV && frame->hw_frames_ctx &&
        ((AVHWFramesContext *)frame->hw_frames_ctx->data)->device_ctx == (AVHWDeviceContext *)qsv->data &&
        sdk_runtime_loaded() && !stat(argv[1], &after) && same_source(&before, &after);
    if (ok)
        printf("{\"scope\":\"first EL AU initialization only, not sample equality or Kodi playback\",\"variant\":\"%s\",\"actual_helper_first_au_reused\":true,\"hardware_qsv_frame\":true,\"cpu_download_used\":false,\"pass\":true}\n", argv[4]);
done:
    const char *saved = failure_stage;
    STAGE("standalone_decoder_destroy");
    av_frame_free(&frame); avcodec_free_context(&decoder);
    STAGE("standalone_devices_release");
    av_buffer_unref(&qsv); av_buffer_unref(&vaapi);
    av_packet_free(&first_au); avcodec_parameters_free(&first_parameters);
    STAGE(saved);
    if (progress_fd >= 0) close(progress_fd);
    return ok ? 0 : diagnostic_failure(1);
}
