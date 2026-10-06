/* Synthetic diagnostic producer/readback only. Production scaler has no maps. */
#define _POSIX_C_SOURCE 200809L
#include "native_vaapi_el_scaler.h"
#include <va/va_drm.h>
#include <va/va_vpp.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <time.h>
static VADisplay display;
static int device=-1,initialized,mapped,image_live;
static VASurfaceID input=VA_INVALID_ID;
static VAImage image;
static struct yb_vaapi_el_scaler *scaler;
static FILE *dump;
static unsigned input_width,input_height;
struct counters { uint64_t client,render,video,enhance; unsigned valid; };
static struct counters sample_counters(void)
{
    struct counters c={0}; char path[80],line[256],unit[8];
    if(snprintf(path,sizeof(path),"/proc/self/fdinfo/%d",device)<0)return c;
    FILE *f=fopen(path,"r"); if(!f)return c;
    unsigned mask=0;
    while(fgets(line,sizeof(line),f)) {
        uint64_t value=0;
        if(sscanf(line,"drm-client-id: %" SCNu64,&value)==1){c.client=value;mask|=1U;}
        if(sscanf(line,"drm-engine-render: %" SCNu64 " %7s",&value,unit)==2&&!strcmp(unit,"ns")){c.render=value;mask|=2U;}
        if(sscanf(line,"drm-engine-video: %" SCNu64 " %7s",&value,unit)==2&&!strcmp(unit,"ns")){c.video=value;mask|=4U;}
        if(sscanf(line,"drm-engine-video-enhance: %" SCNu64 " %7s",&value,unit)==2&&!strcmp(unit,"ns")){c.enhance=value;mask|=8U;}
    }
    (void)fclose(f); c.valid=mask==15U; return c;
}
static uint64_t now(clockid_t clock)
{
    struct timespec t;
    if(clock_gettime(clock,&t)||t.tv_sec<0||t.tv_nsec<0||t.tv_nsec>=1000000000||
       (uint64_t)t.tv_sec>(UINT64_MAX-UINT64_C(999999999))/UINT64_C(1000000000))return 0;
    return (uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
}
static int cleanup(void)
{
    int okay=1;
    if (mapped) { okay &= vaUnmapBuffer(display,image.buf)==VA_STATUS_SUCCESS; mapped=0; }
    int status=yb_vaapi_el_scaler_destroy(&scaler);
    if (status!=YB_VPP_OK) {
        /* No unsafe input recycling or old-output sync after failed context.
         * This standalone probe owns its display; no Kodi display is touched. */
        if (initialized && vaTerminate(display)==VA_STATUS_SUCCESS) {
            initialized=0;
            okay &= yb_vaapi_el_scaler_abandon_after_display_teardown(&scaler,1)==0;
            input=VA_INVALID_ID; image_live=0;
        } else okay=0;
    } else {
        if (image_live) { okay &= vaDestroyImage(display,image.image_id)==VA_STATUS_SUCCESS; image_live=0; }
        if (input!=VA_INVALID_ID) { okay &= vaDestroySurfaces(display,&input,1)==VA_STATUS_SUCCESS; input=VA_INVALID_ID; }
        if (initialized) { okay &= vaTerminate(display)==VA_STATUS_SUCCESS; initialized=0; }
    }
    if (device>=0) { okay &= close(device)==0; device=-1; }
    if (dump) { okay &= fclose(dump)==0; dump=NULL; }
    return okay;
}
static void fail(const char *why)
{ fprintf(stderr,"VA scaler probe failed: %s\n",why); (void)cleanup(); exit(1); }
static void check(VAStatus status,const char *name)
{ if (status!=VA_STATUS_SUCCESS) fail(name); }
#define VA_CHECK(x) check((x),#x)
static VAImageFormat image_format(void)
{
    int max=vaMaxNumImageFormats(display),count=0,found=0;
    if (max<=0 || max>4096) fail("format capacity");
    VAImageFormat *formats=calloc((size_t)max,sizeof(*formats)),selected={0};
    if (!formats) fail("format allocation");
    VAStatus status=vaQueryImageFormats(display,formats,&count);
    if (status==VA_STATUS_SUCCESS && count>=0 && count<=max)
        for (int i=0;i<count;i++)
            if (formats[i].fourcc==VA_FOURCC_P010 && formats[i].byte_order==VA_LSB_FIRST) {
                selected=formats[i]; found=1; break;
            }
    free(formats);
    if (!found) fail("P010 little endian image unavailable");
    return selected;
}
static void create_image(unsigned width,unsigned height,VAImageFormat *format)
{
    VA_CHECK(vaCreateImage(display,format,(int)width,(int)height,&image)); image_live=1;
    if (image.width!=width || image.height!=height || image.num_planes!=2 ||
        image.format.fourcc!=VA_FOURCC_P010 || image.format.byte_order!=VA_LSB_FIRST ||
        !image.data_size || image.data_size>64U*1024U*1024U) fail("image shape");
    uint64_t start[2],end[2];
    for (unsigned p=0;p<2;p++) {
        unsigned rows=p ? height/2 : height;
        start[p]=image.offsets[p];
        end[p]=start[p]+(uint64_t)(rows-1)*image.pitches[p]+width*2U;
        if (image.pitches[p]<width*2U || end[p]>image.data_size) fail("image extent");
    }
    if (start[0]<end[1] && start[1]<end[0]) fail("image overlap");
}
static unsigned code(unsigned p,unsigned x,unsigned y,unsigned mode)
{
    if (!mode) return !p ? 256U : (x&1U) ? 640U : 384U;
    if(mode==1) return !p ? 64U+(x*17U+y*11U)%800U :
        (x&1U) ? 200U+((x/2U)*5U+y*3U)%600U : 200U+((x/2U)*3U+y*5U)%600U;
    if(mode==2) return !p ? ((x^y)&1U)*1023U : (((x/2U)^y^(x&1U))&1U)*1023U;
    if(!p)return x==input_width/2U&&y==input_height/2U?1023U:0U;
    return x/2U==input_width/4U&&y==input_height/4U ? (x&1U?0U:1023U) : 512U;
}
static void scale_once(VASurfaceID *output)
{
    if(yb_vaapi_el_scaler_submit(scaler,input,UINT64_C(5000000000)))fail("helper submit");
    if(yb_vaapi_el_scaler_finish(scaler,UINT64_C(5000000000),output))fail("helper finish");
    if(*output==VA_INVALID_ID||*output==input)fail("owned output identity");
}
int main(int argc,char **argv)
{
    if (argc!=6 || strncmp(argv[1],"/dev/dri/renderD",16) || strlen(argv[1])!=19 ||
        strspn(argv[1]+16,"0123456789")!=3 || atoi(argv[1]+16)<128 || atoi(argv[1]+16)>255)
        fail("explicit render node argument required");
    unsigned fast=!strcmp(argv[2],"1")?1U:0U;
    if(strcmp(argv[2],"0")&&strcmp(argv[2],"1"))fail("flag must be 0 or 1");
    if(!strcmp(argv[3],"32")&&!strcmp(argv[4],"32")){input_width=32;input_height=32;}
    else if(!strcmp(argv[3],"1920")&&!strcmp(argv[4],"1080")){input_width=1920;input_height=1080;}
    else fail("only 32x32 or 1920x1080 inputs supported");
    unsigned ow=input_width*2U,oh=input_height*2U;
    if(strcmp(argv[5],"-")){dump=fopen(argv[5],"wbx");if(!dump)fail("new dump file required");}
    device=open(argv[1],O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    struct stat st;
    if (device<0 || fstat(device,&st) || !S_ISCHR(st.st_mode) || major(st.st_rdev)!=226 ||
        minor(st.st_rdev)!=(unsigned)atoi(argv[1]+16)) fail("render node identity");
    display=vaGetDisplayDRM(device);
    int major_version=0,minor_version=0;
    if (!display) fail("VA display");
    VA_CHECK(vaInitialize(display,&major_version,&minor_version)); initialized=1;
    const char *vendor=vaQueryVendorString(display);
    if (!vendor || !strstr(vendor,"Intel")) fail("Intel driver required for qualification");
    VASurfaceAttrib attr={0}; attr.type=VASurfaceAttribPixelFormat;
    attr.flags=VA_SURFACE_ATTRIB_SETTABLE; attr.value.type=VAGenericValueTypeInteger;
    attr.value.value.i=(int)VA_FOURCC_P010;
    VA_CHECK(vaCreateSurfaces(display,VA_RT_FORMAT_YUV420_10,input_width,input_height,&input,1,&attr,1));
    struct yb_vaapi_el_scale_config config={input_width,input_height,ow,oh,YB_VPP_BILINEAR,fast,
        VA_SOURCE_RANGE_FULL,
        VA_CHROMA_SITING_VERTICAL_TOP|VA_CHROMA_SITING_HORIZONTAL_LEFT,
        VA_CHROMA_SITING_VERTICAL_CENTER|VA_CHROMA_SITING_HORIZONTAL_LEFT};
    if (yb_vaapi_el_scaler_create(display,&config,&scaler)) fail("borrowed helper create");
    uint32_t raw_caps=yb_vaapi_el_scaler_filter_caps(scaler);
    VAImageFormat format=image_format();
    unsigned fractions[4]={0},constant_mismatches=0,observed_prefix[4][12]={{0}};
    uint64_t wall[3]={0},cpu[3]={0},render[3]={0},video[3]={0},enhance[3]={0};
    unsigned counters_valid=1;
    for (unsigned mode=0;mode<4;mode++) {
        create_image(input_width,input_height,&format);
        unsigned char *data=NULL;
        VA_CHECK(vaMapBuffer(display,image.buf,(void **)&data)); mapped=1;
        if (!data) fail("null upload mapping");
        memset(data,0,image.data_size);
        for (unsigned p=0;p<2;p++) for (unsigned y=0;y<(p?input_height/2U:input_height);y++)
            for (unsigned x=0;x<input_width;x++) {
                unsigned word=code(p,x,y,mode)<<6;
                size_t offset=image.offsets[p]+(size_t)y*image.pitches[p]+x*2U;
                data[offset]=(unsigned char)(word&255U); data[offset+1]=(unsigned char)(word>>8);
            }
        VA_CHECK(vaUnmapBuffer(display,image.buf)); mapped=0;
        VA_CHECK(vaPutImage(display,input,image.image_id,0,0,input_width,input_height,0,0,input_width,input_height));
        VA_CHECK(vaDestroyImage(display,image.image_id)); image_live=0;
        VASurfaceID output=VA_INVALID_ID;
        scale_once(&output);
        if(mode==1) {
            for(unsigned i=0;i<8;i++)scale_once(&output);
            for(unsigned batch=0;batch<3;batch++) {
                struct counters a=sample_counters();
                uint64_t start=now(CLOCK_MONOTONIC),cs=now(CLOCK_PROCESS_CPUTIME_ID);
                for(unsigned i=0;i<64;i++)scale_once(&output);
                uint64_t ce=now(CLOCK_PROCESS_CPUTIME_ID),end=now(CLOCK_MONOTONIC);
                struct counters b=sample_counters();
                if(!start||!cs||end<start||ce<cs)fail("measurement clock");
                wall[batch]=end-start;cpu[batch]=ce-cs;
                if(a.valid&&b.valid&&a.client==b.client&&b.render>=a.render&&b.video>=a.video&&b.enhance>=a.enhance) {
                    render[batch]=b.render-a.render;video[batch]=b.video-a.video;enhance[batch]=b.enhance-a.enhance;
                } else counters_valid=0;
            }
        }
        create_image(ow,oh,&format);
        VA_CHECK(vaGetImage(display,output,0,0,ow,oh,image.image_id));
        VA_CHECK(vaMapBuffer(display,image.buf,(void **)&data)); mapped=1;
        if (!data) fail("null output mapping");
        unsigned index=0;
        for (unsigned p=0;p<2;p++) for (unsigned y=0;y<(p?oh/2U:oh);y++) {
            if(dump&&fwrite(data+image.offsets[p]+(size_t)y*image.pitches[p],ow*2U,1,dump)!=1)fail("dump write");
            for (unsigned x=0;x<ow;x++,index++) {
                size_t offset=image.offsets[p]+(size_t)y*image.pitches[p]+x*2U;
                unsigned word=(unsigned)data[offset]|((unsigned)data[offset+1]<<8);
                fractions[mode] += (word&63U)!=0;
                if (!mode) constant_mismatches += word!=(code(p,x,y,0)<<6);
                if (index<12) observed_prefix[mode][index]=word;
            }
        }
        VA_CHECK(vaUnmapBuffer(display,image.buf)); mapped=0;
        VA_CHECK(vaDestroyImage(display,image.image_id)); image_live=0;
    }
    int gate=!(fractions[0] || fractions[1] || fractions[2] || fractions[3] || constant_mismatches);
    if (!cleanup()) fail("cleanup");
    printf("{\"schema\":\"yblod.vaapi-scaler-flag-probe.v1\",\"complete\":true,\"whole_code_gate_passed\":%s,\"pipeline_fast\":%u,\"input_size\":[%u,%u],\"output_size\":[%u,%u],\"frames\":4,\"words_per_frame\":%u,\"fractional_words\":[%u,%u,%u,%u],\"constant_mismatches\":%u,\"raw_filter_caps\":%u,\"helper_cpu_pixel_transfers\":false,\"probe_upload_readback\":true,\"cleanup_complete\":true,\"batch_iterations\":64,\"warmups\":8,\"untimed_ramp_executions\":9,\"timing_scope\":\"resident ramp input, production helper submit plus finish, excludes upload and readback; not playback\",\"counter_scope\":\"explicit render-node fd client only, cumulative engine busy ns, not frequency normalized\",\"counters_valid\":%s,\"batches\":[",gate?"true":"false",fast,input_width,input_height,ow,oh,ow*oh*3U/2U,fractions[0],fractions[1],fractions[2],fractions[3],constant_mismatches,raw_caps,counters_valid?"true":"false");
    for(unsigned i=0;i<3;i++)printf("%s{\"wall_ns\":%" PRIu64 ",\"cpu_ns\":%" PRIu64 ",\"render_busy_ns\":%" PRIu64 ",\"video_busy_ns\":%" PRIu64 ",\"video_enhance_busy_ns\":%" PRIu64 "}",i?",":"",wall[i],cpu[i],render[i],video[i],enhance[i]);
    printf("],\"output_prefix\":[");
    for (unsigned mode=0;mode<4;mode++) {
        printf("%s[",mode?",":"");
        for (unsigned i=0;i<12;i++) printf("%s%u",i?",":"",observed_prefix[mode][i]);
        putchar(']');
    }
    puts("]}");
    return gate?0:1;
}
