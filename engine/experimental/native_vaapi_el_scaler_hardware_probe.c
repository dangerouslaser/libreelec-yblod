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
static VADisplay display;
static int device=-1,initialized,mapped,image_live;
static VASurfaceID input=VA_INVALID_ID;
static VAImage image;
static struct yb_vaapi_el_scaler *scaler;
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
        !image.data_size || image.data_size>16U*1024U*1024U) fail("image shape");
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
    return !p ? 64U+(x*17U+y*11U)%800U : (x&1U) ? 600U+y*3U : 200U+y*5U;
}
int main(int argc,char **argv)
{
    if (argc!=2 || strncmp(argv[1],"/dev/dri/renderD",16) || strlen(argv[1])!=19 ||
        strspn(argv[1]+16,"0123456789")!=3 || atoi(argv[1]+16)<128 || atoi(argv[1]+16)>255)
        fail("explicit render node argument required");
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
    VA_CHECK(vaCreateSurfaces(display,VA_RT_FORMAT_YUV420_10,32,32,&input,1,&attr,1));
    struct yb_vaapi_el_scale_config config={32,32,64,64,YB_VPP_BILINEAR,1,
        VA_SOURCE_RANGE_FULL,
        VA_CHROMA_SITING_VERTICAL_TOP|VA_CHROMA_SITING_HORIZONTAL_LEFT,
        VA_CHROMA_SITING_VERTICAL_CENTER|VA_CHROMA_SITING_HORIZONTAL_LEFT};
    if (yb_vaapi_el_scaler_create(display,&config,&scaler)) fail("borrowed helper create");
    uint32_t raw_caps=yb_vaapi_el_scaler_filter_caps(scaler);
    VAImageFormat format=image_format();
    unsigned fractions[2]={0},constant_mismatches=0,observed_prefix[2][12]={{0}};
    for (unsigned mode=0;mode<2;mode++) {
        create_image(32,32,&format);
        unsigned char *data=NULL;
        VA_CHECK(vaMapBuffer(display,image.buf,(void **)&data)); mapped=1;
        if (!data) fail("null upload mapping");
        memset(data,0,image.data_size);
        for (unsigned p=0;p<2;p++) for (unsigned y=0;y<(p?16U:32U);y++)
            for (unsigned x=0;x<32;x++) {
                unsigned word=code(p,x,y,mode)<<6;
                size_t offset=image.offsets[p]+(size_t)y*image.pitches[p]+x*2U;
                data[offset]=(unsigned char)(word&255U); data[offset+1]=(unsigned char)(word>>8);
            }
        VA_CHECK(vaUnmapBuffer(display,image.buf)); mapped=0;
        VA_CHECK(vaPutImage(display,input,image.image_id,0,0,32,32,0,0,32,32));
        VA_CHECK(vaDestroyImage(display,image.image_id)); image_live=0;
        if (yb_vaapi_el_scaler_submit(scaler,input,UINT64_C(5000000000))) fail("helper submit");
        VASurfaceID output=VA_INVALID_ID;
        if (yb_vaapi_el_scaler_finish(scaler,UINT64_C(5000000000),&output)) fail("helper finish");
        if (output==VA_INVALID_ID || output==input) fail("owned output identity");
        create_image(64,64,&format);
        VA_CHECK(vaGetImage(display,output,0,0,64,64,image.image_id));
        VA_CHECK(vaMapBuffer(display,image.buf,(void **)&data)); mapped=1;
        if (!data) fail("null output mapping");
        unsigned index=0;
        for (unsigned p=0;p<2;p++) for (unsigned y=0;y<(p?32U:64U);y++)
            for (unsigned x=0;x<64;x++,index++) {
                size_t offset=image.offsets[p]+(size_t)y*image.pitches[p]+x*2U;
                unsigned word=(unsigned)data[offset]|((unsigned)data[offset+1]<<8);
                fractions[mode] += (word&63U)!=0;
                if (!mode) constant_mismatches += word!=(code(p,x,y,0)<<6);
                if (index<12) observed_prefix[mode][index]=word;
            }
        VA_CHECK(vaUnmapBuffer(display,image.buf)); mapped=0;
        VA_CHECK(vaDestroyImage(display,image.image_id)); image_live=0;
    }
    if (fractions[0] || fractions[1] || constant_mismatches) fail("whole-code/constant preservation gate");
    if (!cleanup()) fail("cleanup");
    printf("{\"schema\":\"yblod.borrowed-vaapi-el-scaler.v1\",\"complete\":true,\"input_size\":[32,32],\"output_size\":[64,64],\"frames\":2,\"words_per_frame\":6144,\"fractional_words\":[%u,%u],\"constant_mismatches\":%u,\"raw_filter_caps\":%u,\"helper_cpu_pixel_transfers\":false,\"probe_upload_readback\":true,\"egl_import_tested\":false,\"annex_b_equivalence_proven\":false,\"cleanup_complete\":true,\"output_prefix\":[",fractions[0],fractions[1],constant_mismatches,raw_caps);
    for (unsigned mode=0;mode<2;mode++) {
        printf("%s[",mode?",":"");
        for (unsigned i=0;i<12;i++) printf("%s%u",i?",":"",observed_prefix[mode][i]);
        putchar(']');
    }
    puts("]}");
    return 0;
}
