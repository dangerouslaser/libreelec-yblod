/* Header-only BL/EL preflight: no decoder open, GPU use, or pixel output. */
#define _POSIX_C_SOURCE 200809L
#include "dvbridge_fel.c"
#include <libavformat/avformat.h>
#include <libavutil/log.h>
#include <stdio.h>

static void properties(const struct dvbridge_qsv_properties *p)
{
    printf("{\"width\":%d,\"height\":%d,\"format\":%d,\"chroma_location\":%d,"
           "\"range\":%d,\"primaries\":%d,\"transfer\":%d,\"matrix\":%d,\"sar\":[%d,%d]}",
           p->width,p->height,p->format,p->chroma_location,p->color_range,
           p->color_primaries,p->color_trc,p->colorspace,p->sar_num,p->sar_den);
}

int main(int argc, char **argv)
{
    AVFormatContext *input=NULL;
    AVPacket *packet=NULL;
    struct dvbridge_fel *fel=NULL;
    int pass=0, stream=-1;
    av_log_set_level(AV_LOG_QUIET);
    if (argc!=2 || setenv("DVBRIDGE_FEL_QSV","1",1)) goto done;
    if (avformat_open_input(&input,argv[1],NULL,NULL)<0 ||
        avformat_find_stream_info(input,NULL)<0) goto done;
    stream=av_find_best_stream(input,AVMEDIA_TYPE_VIDEO,-1,-1,NULL,0);
    if (stream<0 || input->streams[stream]->codecpar->codec_id!=AV_CODEC_ID_HEVC) goto done;
    fel=dvbridge_fel_create(input->streams[stream]->codecpar,input->streams[stream]->time_base);
    packet=av_packet_alloc();
    if (!fel || !packet) goto done;
    for (int i=0;i<128 && !fel->num_packets;i++) {
        if (av_read_frame(input,packet)<0) break;
        if (packet->stream_index==stream && !dvbridge_fel_submit(fel,packet)) goto done;
        av_packet_unref(packet);
    }
    if (!fel->num_packets || fel->opened) goto done;
    const AVCodecContext *bc=fel->base_order.context;
    const AVCodecParserContext *bp=fel->base_order.parser;
    struct dvbridge_qsv_properties bl={
        .width=bp->width,.height=bp->height,.format=bp->format,
        .chroma_location=bc->chroma_sample_location,.color_range=bc->color_range,
        .color_primaries=bc->color_primaries,.color_trc=bc->color_trc,.colorspace=bc->colorspace,
        .sar_num=bc->sample_aspect_ratio.num,.sar_den=bc->sample_aspect_ratio.den};
    const struct dvbridge_qsv_properties *el=&fel->packet_properties[0];
    if ((bl.chroma_location!=AVCHROMA_LOC_LEFT && bl.chroma_location!=AVCHROMA_LOC_TOPLEFT) ||
        el->chroma_location!=AVCHROMA_LOC_TOPLEFT || el->format!=AV_PIX_FMT_YUV420P10LE ||
        bl.format!=AV_PIX_FMT_YUV420P10LE || bl.width<=0 || bl.height<=0 ||
        el->width<=0 || el->height<=0) goto done;
    printf("{\"pass\":true,\"decoder_opened\":false,\"bl\":");properties(&bl);
    printf(",\"el\":");properties(el);
    puts(",\"scope\":\"Actual stream BL/EL header metadata only; not decoded pixels or playback\"}");
    pass=1;
done:
    if (!pass) puts("{\"pass\":false,\"scope\":\"Header-only metadata preflight\"}");
    av_packet_free(&packet);
    dvbridge_fel_destroy(fel);
    avformat_close_input(&input);
    return pass?0:1;
}
