/* CPU-only real-helper normalization/queue retry contracts; no GPU. */
#define av_bsf_send_packet mock_bsf_send
#define av_bsf_receive_packet mock_bsf_receive
#define avcodec_send_packet mock_decode_send
#define avcodec_receive_frame mock_decode_receive
#ifndef YB_FEL_SOURCE
#define YB_FEL_SOURCE "dvbridge_fel.c"
#endif
#include YB_FEL_SOURCE
#undef av_bsf_send_packet
#undef av_bsf_receive_packet
#undef avcodec_send_packet
#undef avcodec_receive_frame
#include <assert.h>
#include <stdio.h>
static int normal_send,normal_receive,decoder_send;
static int normalize_failure;
int mock_bsf_send(AVBSFContext *ctx,AVPacket *packet)
{ (void)ctx;(void)packet;++normal_send;return normalize_failure ? AVERROR_INVALIDDATA : 0; }
int mock_bsf_receive(AVBSFContext *ctx,AVPacket *packet)
{ (void)ctx;(void)packet;++normal_receive;return 0; }
int mock_decode_send(AVCodecContext *ctx,const AVPacket *packet)
{ (void)ctx;(void)packet;++decoder_send;return AVERROR(EAGAIN); }
int mock_decode_receive(AVCodecContext *ctx,AVFrame *frame)
{ (void)ctx;(void)frame;return AVERROR(EAGAIN); }
int main(void)
{
    AVPacket *packet=av_packet_alloc();assert(packet&&!av_new_packet(packet,18));
    const uint8_t data[]={0,0,0,1,64,1,0,0,0,1,66,1,0,0,0,1,68,1};
    memcpy(packet->data,data,sizeof(data));packet->pts=123;
    struct dvbridge_fel f={0};
    assert(normalize_qsv_packet(&f,packet)&&!normal_send&&!normal_receive);
    f.qsv=true;f.qsv_normalizer=(AVBSFContext *)(uintptr_t)1;
    assert(normalize_qsv_packet(&f,packet)&&normal_send==1&&normal_receive==1&&f.qsv_inband_headers==7);
    f.opened=true;f.packets[0]=packet;f.num_packets=1;f.num_times=1;
    f.packet_order[0]=0;f.times[0].order=0;f.times[0].pts=123;
    assert(pump(&f)&&pump(&f)&&decoder_send==2&&normal_send==1&&normal_receive==1);
    assert(f.num_packets==1&&packet->pts==123&&f.tokens.count==0);
    normalize_failure=1;assert(!normalize_qsv_packet(&f,packet)&&normal_receive==1);
    AVCodecParameters parameters={.extradata=packet->data,.extradata_size=packet->size};
    assert(qsv_configuration_has_parameters(&parameters));
    parameters.extradata_size=12;assert(!qsv_configuration_has_parameters(&parameters));
    packet->data[5]=0;parameters.extradata_size=18;assert(!qsv_configuration_has_parameters(&parameters));
    av_packet_free(&packet);
    AVCodecParameters *p=avcodec_parameters_alloc();assert(p);
    p->codec_id=AV_CODEC_ID_HEVC;p->codec_type=AVMEDIA_TYPE_VIDEO;p->width=3840;p->height=2160;
    p->extradata=av_mallocz(23+AV_INPUT_BUFFER_PADDING_SIZE);assert(p->extradata);
    p->extradata_size=23;p->extradata[0]=1;p->extradata[21]=3;
    assert(!setenv("DVBRIDGE_FEL_QSV","0",1));
    struct dvbridge_fel *created=dvbridge_fel_create(p,AV_TIME_BASE_Q);assert(created&&!created->qsv_normalizer);
    assert(created->decoder->extradata_size==23&&!memcmp(created->decoder->extradata,p->extradata,23));
    dvbridge_fel_destroy(created);
    assert(!setenv("DVBRIDGE_FEL_QSV","1",1));
    created=dvbridge_fel_create(p,AV_TIME_BASE_Q);assert(created&&created->qsv_normalizer&&!created->qsv_configuration_present);
    assert(!created->decoder->extradata_size&&!created->qsv_normalizer->par_out->extradata_size);
    created->qsv_inband_headers=7;dvbridge_fel_reset(created);assert(!created->qsv_inband_headers);
    dvbridge_fel_destroy(created);
    /* Structural EL configuration fixture: preservation, not SPS conformance. */
    AVPacketSideData *sd=av_packet_side_data_new(&p->coded_side_data,&p->nb_coded_side_data,AV_PKT_DATA_HEVC_CONF,44,0);assert(sd);
    memset(sd->data,0,44);sd->data[0]=1;sd->data[21]=3;sd->data[22]=3;
    for(int i=0;i<3;i++){int pos=23+i*7;sd->data[pos]=32+i;sd->data[pos+2]=1;sd->data[pos+4]=2;sd->data[pos+5]=(32+i)<<1;sd->data[pos+6]=1;}
    created=dvbridge_fel_create(p,AV_TIME_BASE_Q);assert(created&&created->qsv_configuration_present&&created->decoder->extradata_size==18);
    assert(qsv_configuration_has_parameters(created->qsv_normalizer->par_out));
    dvbridge_fel_reset(created);assert(created->qsv_configuration_present);
    dvbridge_fel_destroy(created);
    sd->data[22]=0;sd->size=23;assert(!dvbridge_fel_create(p,AV_TIME_BASE_Q));
    avcodec_parameters_free(&p);
    puts("CPU-only defaultOFF/normalization/failclosed/EAGAIN-token-retry contracts PASS");return 0;
}
