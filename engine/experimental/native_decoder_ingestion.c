/* Offline diagnostic only. Decode a bounded raw HEVC EL window from its start;
 * consume decoder-owned metadata, never manufacture FFmpeg structures from JSON.
 * Output is a private, same-build native instructions object (not a wire ABI).
 */
#define _POSIX_C_SOURCE 200809L
#include "native_dovi_adapter.h"
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/buffer.h>
#include <libavutil/log.h>
#include <libavutil/sha.h>
#include <libavutil/pixfmt.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define LIMIT_BYTES (4U*1024U*1024U)
#define LIMIT_FRAMES 96U
typedef struct { int64_t position; int size; uint32_t ordinal; } packet_identity;
static unsigned error_logs;
static void log_callback(void *context, int level, const char *format, va_list args)
{
    (void)context; (void)format; (void)args;
    /* Do not leak filenames, RPU data or decoder messages to public stdout. */
    if (level <= AV_LOG_WARNING) ++error_logs;
}
static int number(const char *s, uint64_t maximum, uint64_t *value)
{
    char *end; unsigned long long v;
    if (!s || !*s || *s=='-' || *s=='+') return 0;
    for(const char *p=s;*p;++p) if(*p<'0' || *p>'9') return 0;
    errno=0; v=strtoull(s,&end,10);
    if (errno || *end || v>maximum) return 0;
    *value=(uint64_t)v; return 1;
}
static int hex_digest(const char *s, uint8_t result[32])
{
    if (strlen(s)!=64U) return 0;
    for (unsigned i=0;i<32U;++i) {
        unsigned x=0;
        for (unsigned j=0;j<2U;++j) {
            unsigned char c=(unsigned char)s[2U*i+j];
            if(c>='0'&&c<='9') x=x*16U+(unsigned)(c-'0');
            else if(c>='a'&&c<='f') x=x*16U+(unsigned)(c-'a')+10U;
            else return 0;
        }
        result[i]=(uint8_t)x;
    }
    return 1;
}
static void digest_hex(const uint8_t digest[32], char result[65])
{
    static const char digits[]="0123456789abcdef";
    for(unsigned i=0;i<32U;++i) { result[i*2U]=digits[digest[i]>>4]; result[i*2U+1U]=digits[digest[i]&15U]; }
    result[64]=0;
}
static int checked_file(const char *path, int *descriptor, struct stat *state)
{
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(fd<0 || fstat(fd,state)!=0 || !S_ISREG(state->st_mode) || state->st_size<=0 ||
       (uint64_t)state->st_size>LIMIT_BYTES) { if(fd>=0) close(fd); return 0; }
    *descriptor=fd; return 1;
}
static int stable(int fd, const struct stat *original);
static int hash_file(int fd, struct AVSHA *sha, const struct stat *original, uint8_t digest[32])
{
    uint8_t block[65536]; size_t remaining;
    if(original->st_size<=0 || (uint64_t)original->st_size>LIMIT_BYTES || !stable(fd,original) ||
       lseek(fd,0,SEEK_SET)<0 || av_sha_init(sha,256)<0) return 0;
    remaining=(size_t)original->st_size;
    while(remaining) {
        size_t wanted=remaining<sizeof(block)?remaining:sizeof(block);
        ssize_t count=read(fd,block,wanted);
        if(count<=0) return 0;
        av_sha_update(sha,block,(size_t)count); remaining-=(size_t)count;
    }
    if(read(fd,block,1U)!=0 || !stable(fd,original)) return 0;
    av_sha_final(sha,digest); return lseek(fd,0,SEEK_SET)>=0;
}
static int stable(int fd, const struct stat *original)
{
    struct stat now;
    return fstat(fd,&now)==0 && now.st_dev==original->st_dev && now.st_ino==original->st_ino &&
        now.st_size==original->st_size && now.st_mtim.tv_sec==original->st_mtim.tv_sec &&
        now.st_mtim.tv_nsec==original->st_mtim.tv_nsec && now.st_ctim.tv_sec==original->st_ctim.tv_sec &&
        now.st_ctim.tv_nsec==original->st_ctim.tv_nsec;
}
static int frame_matches(AVFrame *frame, struct AVSHA *sha, const uint8_t expected[3][32])
{
    if(frame->width!=1920 || frame->height!=1080 || frame->format!=AV_PIX_FMT_YUV420P10LE ||
       frame->flags&AV_FRAME_FLAG_CORRUPT || frame->decode_error_flags) return 0;
    for(unsigned p=0;p<3U;++p) {
        unsigned width=p?960U:1920U, height=p?540U:1080U;
        uint8_t actual[32];
        if(!frame->data[p] || frame->linesize[p]<(int)(width*2U) || av_sha_init(sha,256)<0) return 0;
        for(unsigned row=0;row<height;++row) av_sha_update(sha,frame->data[p]+(size_t)row*(size_t)frame->linesize[p],width*2U);
        av_sha_final(sha,actual);
        if(memcmp(actual,expected[p],32U)!=0) return 0;
    }
    return 1;
}
static int read_packet(void *opaque, uint8_t *buffer, int bytes)
{
    int fd=*(int *)opaque; ssize_t got=read(fd,buffer,(size_t)bytes);
    return got>0?(int)got:got==0?AVERROR_EOF:AVERROR(errno);
}
static int64_t seek_input(void *opaque, int64_t offset, int whence)
{
    int fd=*(int *)opaque;
    if(whence==AVSEEK_SIZE) { struct stat s; return fstat(fd,&s)==0?s.st_size:AVERROR(errno); }
    /* Raw HEVC demuxer probing may rewind bytes, but the decoder never seeks. */
    if(whence&AVSEEK_FORCE) whence&=~AVSEEK_FORCE;
    if(whence!=SEEK_SET && whence!=SEEK_CUR && whence!=SEEK_END) return AVERROR(EINVAL);
    off_t p=lseek(fd,(off_t)offset,whence); return p<0?AVERROR(errno):(int64_t)p;
}
int main(int argc, char **argv)
{
    /* window nal ordinal packet-pos packet-size window-sha Y-sha Cb-sha Cr-sha output */
    int exit_status=1, fd=-1, nal_fd=-1, output_fd=-1, created=0, target_seen=0;
    const char *failure_stage="runtime_abi";
    unsigned frame_count=0, packet_count=0; uint64_t target, position, packet_size;
    size_t observed_raw_bytes=0U, expected_raw_bytes=0U;
    int64_t observed_packet_position=-1;
    int observed_packet_size=-1;
    struct stat source_state,nal_state,output_state;
    int output_identity=0;
    uint8_t expected_window[32], expected_planes[3][32], initial_hash[32], final_hash[32];
    uint8_t nal[65536]; ssize_t nal_bytes;
    struct AVSHA *sha=NULL; AVFormatContext *format=NULL; AVIOContext *io=NULL;
    AVCodecContext *decoder=NULL; AVFrame *frame=NULL; AVPacket *packet=NULL;
    yb_dovi_integer_instructions instructions; memset(&instructions,0,sizeof(instructions));
    av_log_set_callback(log_callback);
    if(avcodec_version()!=LIBAVCODEC_VERSION_INT || avformat_version()!=LIBAVFORMAT_VERSION_INT ||
       avutil_version()!=LIBAVUTIL_VERSION_INT || yb_dovi_adapter_abi_version()!=1U ||
       yb_dovi_adapter_sizeof_instructions()!=sizeof(instructions)) goto done;
    failure_stage="arguments";
    if(argc!=11 || !number(argv[3],LIMIT_FRAMES-1U,&target) || !number(argv[4],LIMIT_BYTES,&position) ||
       !number(argv[5],LIMIT_BYTES,&packet_size) || !packet_size || !hex_digest(argv[6],expected_window) ||
       !hex_digest(argv[7],expected_planes[0]) || !hex_digest(argv[8],expected_planes[1]) ||
       !hex_digest(argv[9],expected_planes[2])) goto done;
    failure_stage="input_identity"; sha=av_sha_alloc();
    if(!sha || !checked_file(argv[1],&fd,&source_state) || !checked_file(argv[2],&nal_fd,&nal_state) ||
       nal_state.st_size>(off_t)sizeof(nal) || position>(uint64_t)source_state.st_size ||
       packet_size>(uint64_t)source_state.st_size-position || !hash_file(fd,sha,&source_state,initial_hash) ||
       memcmp(initial_hash,expected_window,32U)) goto done;
    failure_stage="expected_nal"; nal_bytes=read(nal_fd,nal,(size_t)nal_state.st_size);
    /* Expected file is precisely the two-byte HEVC NAL header plus EPB payload;
     * no Annex-B start code or de-escaping is guessed here. */
    if(nal_bytes!=nal_state.st_size || nal_bytes<3 || (nal[0]&0x80U)!=0U || ((nal[0]>>1)&63U)!=62U ||
       (nal[0]&1U)!=0U || (nal[1]>>3)!=0U || (nal[1]&7U)!=1U) goto done;
    expected_raw_bytes=(size_t)nal_bytes-2U;
    failure_stage="demux_open"; format=avformat_alloc_context();
    uint8_t *io_buffer=av_malloc(65536U);
    if(!format || !io_buffer) { av_free(io_buffer); goto done; }
    io=avio_alloc_context(io_buffer,65536,0,&fd,read_packet,NULL,seek_input);
    if(!io) { av_free(io_buffer); goto done; }
    format->pb=io; format->flags|=AVFMT_FLAG_CUSTOM_IO;
    format->probesize=LIMIT_BYTES; format->max_analyze_duration=0;
    const AVInputFormat *input=av_find_input_format("hevc");
    if(!input || avformat_open_input(&format,NULL,input,NULL)<0 || format->nb_streams!=1U ||
       format->streams[0]->codecpar->codec_id!=AV_CODEC_ID_HEVC) goto done;
    failure_stage="decoder_open"; const AVCodec *codec=avcodec_find_decoder_by_name("hevc");
    decoder=codec?avcodec_alloc_context3(codec):NULL;
    if(!decoder || avcodec_parameters_to_context(decoder,format->streams[0]->codecpar)<0) goto done;
    decoder->thread_count=1; decoder->thread_type=0;
    decoder->max_pixels=1920*1080;
    decoder->err_recognition=AV_EF_CRCCHECK|AV_EF_EXPLODE|AV_EF_BITSTREAM|AV_EF_BUFFER;
    decoder->flags|=AV_CODEC_FLAG_COPY_OPAQUE;
    if(avcodec_open2(decoder,codec,NULL)<0) goto done;
    frame=av_frame_alloc(); packet=av_packet_alloc();
    if(!frame || !packet) goto done;
    int draining=0;
    while(!target_seen) {
        failure_stage="receive_frame";
        int ret=avcodec_receive_frame(decoder,frame);
        if(ret==0) {
            failure_stage="frame_validation";
            AVFrameSideData *raw=av_frame_get_side_data(frame,AV_FRAME_DATA_DOVI_RPU_BUFFER);
            AVFrameSideData *metadata=av_frame_get_side_data(frame,AV_FRAME_DATA_DOVI_METADATA);
            if(frame_count>=LIMIT_FRAMES || frame->width!=1920 || frame->height!=1080 ||
               frame->format!=AV_PIX_FMT_YUV420P10LE || frame->flags&AV_FRAME_FLAG_CORRUPT ||
               frame->decode_error_flags || error_logs || (!frame_count && (!raw || !metadata))) goto done;
            if(frame_count==(unsigned)target) {
                failure_stage="target_raw_presence";
                if(!raw) goto done;
                failure_stage="target_metadata_presence";
                if(!metadata) goto done;
                observed_raw_bytes=raw->size;
                failure_stage="target_rpu_size";
                if(raw->size!=(size_t)nal_bytes-2U) goto done;
                failure_stage="target_rpu_bytes";
                if(memcmp(raw->data,nal+2,raw->size)) goto done;
                failure_stage="target_opaque_presence";
                if(!frame->opaque_ref) goto done;
                failure_stage="target_opaque_size";
                if(frame->opaque_ref->size!=sizeof(packet_identity)) goto done;
                packet_identity id; memcpy(&id,frame->opaque_ref->data,sizeof(id));
                observed_packet_position=id.position; observed_packet_size=id.size;
                failure_stage="target_packet_identity";
                if(id.position!=(int64_t)position || id.size!=(int)packet_size) goto done;
                failure_stage="target_plane_identity";
                if(!frame_matches(frame,sha,expected_planes)) goto done;
                failure_stage="metadata_adapter";
                if(yb_dovi_to_integer_configs(metadata->data,metadata->size,&instructions)!=YB_DOVI_ADAPTER_OK) goto done;
                target_seen=1;
            }
            ++frame_count; av_frame_unref(frame); continue;
        }
        if(ret==AVERROR_EOF || ret!=AVERROR(EAGAIN) || draining) goto done;
        failure_stage="read_packet"; ret=av_read_frame(format,packet);
        if(ret==AVERROR_EOF) { draining=1; if(avcodec_send_packet(decoder,NULL)<0) goto done; continue; }
        if(ret<0 || packet_count>=LIMIT_FRAMES || packet->stream_index!=0 || packet->size<=0 ||
           (unsigned)packet->size>LIMIT_BYTES || packet->pos<0 || error_logs) goto done;
        av_buffer_unref(&packet->opaque_ref);
        packet->opaque_ref=av_buffer_alloc(sizeof(packet_identity));
        if(!packet->opaque_ref) goto done;
        packet_identity id={packet->pos,packet->size,packet_count};
        memcpy(packet->opaque_ref->data,&id,sizeof(id)); ++packet_count;
        failure_stage="send_packet"; if(avcodec_send_packet(decoder,packet)<0) goto done;
        av_packet_unref(packet);
    }
    failure_stage="final_input_identity";
    if(error_logs || !stable(fd,&source_state) || !stable(nal_fd,&nal_state) ||
       !hash_file(fd,sha,&source_state,final_hash) || memcmp(final_hash,initial_hash,32U)) goto done;
    failure_stage="output_write"; output_fd=open(argv[10],O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(output_fd<0) goto done;
    created=1;
    if(fstat(output_fd,&output_state)!=0 || !S_ISREG(output_state.st_mode)) goto done;
    output_identity=1;
    if(write(output_fd,&instructions,sizeof(instructions))!=(ssize_t)sizeof(instructions) || fsync(output_fd)!=0) goto done;
    if(close(output_fd)!=0) { output_fd=-1; goto done; } output_fd=-1;
    uint8_t config_hash[32]; char config_hex[65];
    if(av_sha_init(sha,256)<0) goto done;
    av_sha_update(sha,(const uint8_t *)&instructions,sizeof(instructions)); av_sha_final(sha,config_hash);
    digest_hex(config_hash,config_hex);
    printf("{\"schema\":\"yblod.native-decoder-ingestion.v1\",\"status\":\"complete\","
           "\"local_presentation_index\":%" PRIu64 ",\"frames_received\":%u,\"packets_sent\":%u,"
           "\"original_pts_verified\":false,\"decoder_metadata\":true,\"raw_rpu_exact\":true,"
           "\"el_active_planes_exact\":true,\"crc_requested\":true,\"warning_or_error_logs\":%u,"
           "\"adapter_abi\":%u,\"instructions_bytes\":%zu,\"instructions_sha256\":\"%s\","
           "\"avcodec_version\":%u,\"avformat_version\":%u,\"avutil_version\":%u}\n",
           target,frame_count,packet_count,error_logs,yb_dovi_adapter_abi_version(),sizeof(instructions),config_hex,
           avcodec_version(),avformat_version(),avutil_version());
    exit_status=0;
done:
    if(output_fd>=0) close(output_fd);
    if(exit_status && created && output_identity) {
        struct stat current;
        if(lstat(argv[10],&current)==0 && current.st_dev==output_state.st_dev &&
           current.st_ino==output_state.st_ino && S_ISREG(current.st_mode)) unlink(argv[10]);
    }
    av_packet_free(&packet); av_frame_free(&frame); avcodec_free_context(&decoder);
    avformat_close_input(&format);
    if(io) { av_freep(&io->buffer); avio_context_free(&io); }
    av_free(sha); if(fd>=0) close(fd); if(nal_fd>=0) close(nal_fd);
    if(exit_status) printf("{\"schema\":\"yblod.native-decoder-ingestion.v1\",\"status\":\"rejected\","
       "\"failure_stage\":\"%s\",\"frames_received\":%u,\"packets_sent\":%u,\"warning_or_error_logs\":%u,"
       "\"target_raw_bytes\":%zu,\"expected_raw_bytes\":%zu,\"target_packet_position\":%" PRId64 ","
       "\"target_packet_size\":%d}\n",
       failure_stage,frame_count,packet_count,error_logs,observed_raw_bytes,expected_raw_bytes,
       observed_packet_position,observed_packet_size);
    return exit_status;
}
