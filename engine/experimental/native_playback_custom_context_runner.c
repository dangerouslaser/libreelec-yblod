#define _POSIX_C_SOURCE 200809L
#include "native_playback_context.h"
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
#include <libavutil/dovi_meta.h>
#include <libavutil/pixfmt.h>
#include <va/va_vpp.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <fcntl.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
/* Public fixture owner is a genuine retained FFmpeg VA allocation, not Kodi's
 * allocator/pool implementation. This exercises the explicit custom ABI only. */
struct fixture_owner { AVFrame *storage; VADisplay display; uint64_t generation; uint32_t width,height; int quarantined; };
static unsigned owners_released;
static int owner_validate(void *opaque,VADisplay display,VASurfaceID surface,uint64_t generation,uint32_t w,uint32_t h)
{
 struct fixture_owner *o=opaque;
 return o && o->storage && !o->quarantined && o->display==display && o->generation==generation &&
  o->width==w && o->height==h && (uintptr_t)o->storage->data[3]==(uintptr_t)surface;
}
static void owner_quarantine(void *opaque) { if(opaque)((struct fixture_owner *)opaque)->quarantined=1; }
static void owner_free(void *opaque,uint8_t *data)
{ (void)data;struct fixture_owner *o=opaque;if(o){av_frame_free(&o->storage);free(o);owners_released++;} }
static AVFrame *property_snapshot(const AVFrame *source)
{
 AVFrameSideData *side=av_frame_get_side_data(source,AV_FRAME_DATA_DOVI_METADATA);
 if(!side||!side->data||!side->size||side->size>1024U*1024U)return NULL;
 AVFrame *copy=av_frame_alloc();if(!copy)return NULL;
 copy->format=source->format;copy->width=source->width;copy->height=source->height;copy->data[3]=source->data[3];
 copy->pts=source->pts;copy->best_effort_timestamp=source->best_effort_timestamp;copy->time_base=source->time_base;
 copy->chroma_location=source->chroma_location;copy->flags=source->flags;copy->color_range=source->color_range;
 copy->color_primaries=source->color_primaries;copy->color_trc=source->color_trc;copy->colorspace=source->colorspace;
 AVFrameSideData *out=av_frame_new_side_data(copy,AV_FRAME_DATA_DOVI_METADATA,side->size);
 if(!out){av_frame_free(&copy);return NULL;}memcpy(out->data,side->data,side->size);return copy;
}
static int extension(const char *all,const char *wanted)
{
    if(!all) return 0;
    size_t n=strlen(wanted);const char *p=all;
    while((p=strstr(p,wanted))) {if((p==all||p[-1]==' ')&&(p[n]==' '||!p[n])) return 1;p+=n;}return 0;
}
static int node_valid(const char *node)
{
    const char *prefix="/dev/dri/renderD";if(strncmp(node,prefix,strlen(prefix))) return 0;
    const char *n=node+strlen(prefix);return strlen(n)==3&&strspn(n,"0123456789")==3&&atoi(n)>=128&&atoi(n)<=255;
}
static char *shader_read(const char *path)
{
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);struct stat before,after;char *text=NULL;
    if(fd<0) return NULL;
    if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<=0||before.st_size>65536) goto done;
    size_t size=(size_t)before.st_size,used=0;text=malloc(size+1);if(!text) goto done;
    while(used<size) {ssize_t n=read(fd,text+used,size-used);if(n<=0) {free(text);text=NULL;goto done;}used+=(size_t)n;}
    if(fstat(fd,&after)||after.st_size!=before.st_size||after.st_ino!=before.st_ino||after.st_dev!=before.st_dev||
        after.st_mtim.tv_sec!=before.st_mtim.tv_sec||after.st_mtim.tv_nsec!=before.st_mtim.tv_nsec||memchr(text,0,size)) {free(text);text=NULL;goto done;}
    text[size]=0;
done:close(fd);return text;
}
enum { WIDTH=64,HEIGHT=64,EL_WIDTH=32,EL_HEIGHT=32 };
typedef struct {AVDOVIMetadata meta;AVDOVIRpuDataHeader header;AVDOVIDataMapping mapping;AVDOVIColorMetadata colour;AVDOVIDmData ext;} Fixture;
static uint16_t base_planes[3][WIDTH*HEIGHT],reconstructed[3][WIDTH*HEIGHT];
static float expected[2][WIDTH*HEIGHT*4],actual[WIDTH*HEIGHT*4];
static unsigned guide_influenced_samples,nonzero_residual_samples;
static Fixture metadata;
static yb_playback_frame_descriptor association;
static yb_playback_metadata cpu_metadata;
static unsigned clamp_index(int p,unsigned extent){return p<0?0U:(unsigned)p>=extent?extent-1U:(unsigned)p;}
static unsigned guide_at(unsigned x,unsigned y){
 unsigned rows[2];
 for(unsigned dy=0;dy<2;dy++){
  unsigned row=2U*y+dy;
  unsigned left=base_planes[0][row*WIDTH+clamp_index((int)(2U*x)-1,WIDTH)];
  unsigned centre=base_planes[0][row*WIDTH+2U*x];
  unsigned right=base_planes[0][row*WIDTH+clamp_index((int)(2U*x)+1,WIDTH)];
  rows[dy]=(left+2U*centre+right+2U)/4U;
 }
 return (rows[0]+rows[1]+1U)/2U;
}
static float chroma_at(unsigned component,unsigned x,unsigned y){
 unsigned cw=WIDTH/2U,ch=HEIGHT/2U,x0=x/2U,x1=clamp_index((int)x0+1,cw);
 int iy=y==0U?-1:(int)((2U*y-1U)/4U);
 unsigned y0=clamp_index(iy,ch),y1=clamp_index(iy+1,ch),wx=x%2U,wy=y%2U?1U:3U;
 uint32_t n=(uint32_t)reconstructed[component][y0*cw+x0]*(2U-wx)*(4U-wy)
 +(uint32_t)reconstructed[component][y1*cw+x0]*(2U-wx)*wy
 +(uint32_t)reconstructed[component][y0*cw+x1]*wx*(4U-wy)
 +(uint32_t)reconstructed[component][y1*cw+x1]*wx*wy;
 return (float)n/32768.0f;
}
static int prepare_cpu(unsigned fixture){
 memset(&metadata,0,sizeof(metadata));
 metadata.meta.header_offset=offsetof(Fixture,header);metadata.meta.mapping_offset=offsetof(Fixture,mapping);
 metadata.meta.color_offset=offsetof(Fixture,colour);metadata.meta.ext_block_offset=offsetof(Fixture,ext);metadata.meta.ext_block_size=sizeof(metadata.ext);
 metadata.header.rpu_type=2;metadata.header.rpu_format=18;metadata.header.vdr_rpu_profile=1;metadata.header.coef_log2_denom=23;
 metadata.header.vdr_rpu_normalized_idc=1;metadata.header.bl_bit_depth=10;metadata.header.el_bit_depth=10;metadata.header.vdr_bit_depth=12;
 metadata.mapping.num_x_partitions=metadata.mapping.num_y_partitions=1;metadata.mapping.nlq_method_idc=AV_DOVI_NLQ_LINEAR_DZ;metadata.mapping.nlq_pivots[1]=1023;
 for(unsigned c=0;c<3;c++){
  AVDOVIReshapingCurve *curve=&metadata.mapping.curves[c];curve->num_pivots=2;curve->pivots[1]=1023;
  curve->mapping_idc[0]=AV_DOVI_MAPPING_POLYNOMIAL;curve->poly_order[0]=1;curve->poly_coef[0][1]=INT64_C(1)<<23;
  metadata.mapping.nlq[c].nlq_offset=512;metadata.mapping.nlq[c].linear_deadzone_slope=2048;metadata.mapping.nlq[c].vdr_in_max=1025;
  metadata.colour.ycc_to_rgb_offset[c]=(AVRational){0,1<<28};
 }
 for(unsigned c=1;c<3;c++){
  AVDOVIReshapingCurve *curve=&metadata.mapping.curves[c];
  curve->mapping_idc[0]=AV_DOVI_MAPPING_MMR;curve->mmr_order[0]=1;
  curve->mmr_coef[0][0][0]=INT64_C(1)<<(c==1?21:20);
  curve->mmr_coef[0][0][c]=INT64_C(1)<<23;
 }
 metadata.colour.signal_eotf=65535;metadata.colour.signal_bit_depth=12;metadata.colour.signal_full_range_flag=1;
 for(unsigned i=0;i<9;i++){metadata.colour.ycc_to_rgb_matrix[i]=(AVRational){i%4?0:8192,8192};metadata.colour.rgb_to_lms_matrix[i]=(AVRational){i%4?0:16384,16384};}
 memset(&association,0,sizeof(association));association.version=1;
 association.width=association.el_scaled_width=WIDTH;association.height=association.el_scaled_height=HEIGHT;
 association.guide_width=WIDTH/2;association.guide_height=HEIGHT/2;
 association.bl_pts=association.el_pts=100000;association.bl_timebase_num=association.el_timebase_num=1;association.bl_timebase_den=association.el_timebase_den=1000000;
 memset(association.frame_id,1,32);memcpy(association.metadata_frame_id,association.frame_id,32);memcpy(association.el_frame_id,association.frame_id,32);memcpy(association.guide_frame_id,association.frame_id,32);
 memset(association.preparation_id,2,32);memcpy(association.guide_preparation_id,association.preparation_id,32);memset(association.enhancement_scale_id,3,32);
 association.input_native_depth=10;association.colour_route=YB_PLAYBACK_COLOUR_INHERITED;association.source_dm_uncompressed=0;
 if(yb_playback_metadata_init(&association,&metadata,sizeof(metadata),NULL,&cpu_metadata))return 0;
 for(unsigned c=0;c<3;c++)for(unsigned i=0;i<(c?WIDTH*HEIGHT/4U:WIDTH*HEIGHT);i++)base_planes[c][i]=(uint16_t)((64U+i*17U+c*113U)%1024U);
 for(unsigned c=0;c<3;c++)for(unsigned i=0;i<(c?WIDTH*HEIGHT/4U:WIDTH*HEIGHT);i++){
  int64_t samples[3]={0,0,0};unsigned x=i%(WIDTH/2U),y=i/(WIDTH/2U);
  if(c){samples[0]=guide_at(x,y);samples[1]=base_planes[1][i];samples[2]=base_planes[2][i];}
  else samples[0]=base_planes[0][i];
  uint16_t mapped=0;
  if(yb_map_sample(&cpu_metadata.integer.mapping,(int32_t)c,samples,&mapped)||
     yb_compose(&cpu_metadata.integer.nlq[c],mapped,512+(int64_t)fixture,12,&reconstructed[c][i]))return 0;
  if(c){uint16_t without_guide=0;samples[0]=0;
   if(yb_map_sample(&cpu_metadata.integer.mapping,(int32_t)c,samples,&without_guide))return 0;
   guide_influenced_samples+=(unsigned)(mapped!=without_guide);
  }
  int64_t residual=0;
  if(yb_nlq(&cpu_metadata.integer.nlq[c],512+(int64_t)fixture,&residual))return 0;
  nonzero_residual_samples+=(unsigned)(residual!=0);
 }
 for(unsigned y=0;y<HEIGHT;y++)for(unsigned x=0;x<WIDTH;x++){
  unsigned i=y*WIDTH+x;expected[fixture][4U*i]=(float)reconstructed[0][i]/4096.0f;
  expected[fixture][4U*i+1U]=chroma_at(1,x,y);expected[fixture][4U*i+2U]=chroma_at(2,x,y);expected[fixture][4U*i+3U]=1.0f;
 }
 return 1;
}
static AVFrame *create_frame(AVBufferRef *device,unsigned width,unsigned height,int enhancement){
 AVBufferRef *pool=av_hwframe_ctx_alloc(device);AVFrame *frame=NULL,*software=NULL;
 if(!pool)return NULL;
 AVHWFramesContext *frames=(AVHWFramesContext *)pool->data;
 frames->format=AV_PIX_FMT_VAAPI;frames->sw_format=AV_PIX_FMT_P010LE;frames->width=(int)width;frames->height=(int)height;frames->initial_pool_size=2;
 if(av_hwframe_ctx_init(pool)<0)goto done;
 frame=av_frame_alloc();software=av_frame_alloc();if(!frame||!software)goto done;
 if(av_hwframe_get_buffer(pool,frame,0)<0)goto fail;
 software->format=AV_PIX_FMT_P010LE;software->width=(int)width;software->height=(int)height;
 if(av_frame_get_buffer(software,32)<0)goto fail;
 for(unsigned y=0;y<height;y++){
  uint16_t *row=(uint16_t *)(software->data[0]+(size_t)y*(size_t)software->linesize[0]);
  for(unsigned x=0;x<width;x++)row[x]=(uint16_t)((enhancement?(unsigned)enhancement:base_planes[0][y*width+x])<<6U);
 }
 for(unsigned y=0;y<height/2U;y++){
  uint16_t *row=(uint16_t *)(software->data[1]+(size_t)y*(size_t)software->linesize[1]);
  for(unsigned x=0;x<width/2U;x++)for(unsigned c=0;c<2;c++)row[2U*x+c]=(uint16_t)((enhancement?(unsigned)enhancement:base_planes[c+1U][y*(width/2U)+x])<<6U);
 }
 if(av_hwframe_transfer_data(frame,software,0)<0)goto fail;
 frame->pts=100000;frame->best_effort_timestamp=100000;frame->time_base=(AVRational){1,1000000};
 frame->chroma_location=enhancement?AVCHROMA_LOC_TOPLEFT:AVCHROMA_LOC_LEFT;
 if(!enhancement){
  AVFrameSideData *side=av_frame_new_side_data(frame,AV_FRAME_DATA_DOVI_METADATA,sizeof(metadata));
  if(!side)goto fail;
  memcpy(side->data,&metadata,sizeof(metadata));
 }
 goto done;
fail:av_frame_free(&frame);
done:av_frame_free(&software);av_buffer_unref(&pool);return frame;
}
typedef void (*GLProc)(void);
#define GL_PROCS(X) X(GetError,PFNGLGETERRORPROC) X(GenFramebuffers,PFNGLGENFRAMEBUFFERSPROC) X(BindFramebuffer,PFNGLBINDFRAMEBUFFERPROC) X(FramebufferTexture2D,PFNGLFRAMEBUFFERTEXTURE2DPROC) X(CheckFramebufferStatus,PFNGLCHECKFRAMEBUFFERSTATUSPROC) X(ReadPixels,PFNGLREADPIXELSPROC) X(DeleteFramebuffers,PFNGLDELETEFRAMEBUFFERSPROC)
#define DECLARE(n,t) t n;
struct gl_api{GL_PROCS(DECLARE)};
#undef DECLARE
static int restored(EGLDisplay display,EGLContext context){
 return eglGetCurrentDisplay()==display&&eglGetCurrentContext()==context&&eglQueryAPI()==EGL_OPENGL_ES_API&&eglGetCurrentSurface(EGL_DRAW)==EGL_NO_SURFACE&&eglGetCurrentSurface(EGL_READ)==EGL_NO_SURFACE;
}
static int execute(const char *node,char *prep,char *composer,char *ycc){
 int ok=0,fd=-1,initialized=0,current=0;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
 struct stat requested;struct gl_api gl={0};GLuint fbo=0;AVBufferRef *device=NULL;AVFrame *base=NULL,*el=NULL;
 yb_native_playback_context *playback=NULL;AVFrame *snapshot=NULL;AVBufferRef *owner_ref=NULL;
    fd=open(node,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0||fstat(fd,&requested)||!S_ISCHR(requested.st_mode)||major(requested.st_rdev)!=226||minor(requested.st_rdev)!=(unsigned)atoi(node+strlen("/dev/dri/renderD"))) goto cleanup;
    const char *client=eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    if(eglGetError()!=EGL_SUCCESS||!extension(client,"EGL_EXT_platform_device")||
        !(extension(client,"EGL_EXT_device_base")||(extension(client,"EGL_EXT_device_enumeration")&&extension(client,"EGL_EXT_device_query")))) goto cleanup;
    PFNEGLQUERYDEVICESEXTPROC query_devices=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC device_string=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    PFNEGLQUERYDISPLAYATTRIBEXTPROC display_attribute=(PFNEGLQUERYDISPLAYATTRIBEXTPROC)eglGetProcAddress("eglQueryDisplayAttribEXT");
    if(!query_devices||!device_string||!platform_display||!display_attribute) goto cleanup;
    EGLint count=0,returned=0;EGLDeviceEXT listed[32],selected=EGL_NO_DEVICE_EXT;
    if(!query_devices(0,NULL,&count)||count<1||count>32||!query_devices(count,listed,&returned)||count!=returned) goto cleanup;
    unsigned matches=0;
    for(EGLint i=0;i<count;++i) {
        const char *ext=device_string(listed[i],EGL_EXTENSIONS);
        if(eglGetError()!=EGL_SUCCESS||!extension(ext,"EGL_EXT_device_drm_render_node")||extension(ext,"EGL_MESA_device_software")) continue;
        const char *path=device_string(listed[i],EGL_DRM_RENDER_NODE_FILE_EXT);struct stat candidate;
        if(eglGetError()==EGL_SUCCESS&&path&&!stat(path,&candidate)&&S_ISCHR(candidate.st_mode)&&candidate.st_rdev==requested.st_rdev) {++matches;selected=listed[i];}
    }
    if(matches!=1) goto cleanup;
    display=platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);EGLint egl_major=0,egl_minor=0;
    if(display==EGL_NO_DISPLAY||!eglInitialize(display,&egl_major,&egl_minor)) goto cleanup;
    initialized=1;EGLAttrib egl_device=0;
    if(!display_attribute(display,EGL_DEVICE_EXT,&egl_device)||(EGLDeviceEXT)egl_device!=selected) goto cleanup;
    const char *ext=eglQueryString(display,EGL_EXTENSIONS);
    if(eglGetError()!=EGL_SUCCESS||!extension(ext,"EGL_KHR_surfaceless_context")||!eglBindAPI(EGL_OPENGL_ES_API)) goto cleanup;
    const EGLint config_attributes[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT_KHR,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_MAJOR_VERSION_KHR,3,EGL_CONTEXT_MINOR_VERSION_KHR,1,EGL_NONE};
    EGLConfig config;EGLint configs_count=0;
    if(!eglChooseConfig(display,config_attributes,&config,1,&configs_count)||configs_count!=1) goto cleanup;
    context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    if(context==EGL_NO_CONTEXT||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) goto cleanup;
    current=1;


#define LOAD(n,t) gl.n=(t)eglGetProcAddress("gl" #n);if(!gl.n)goto cleanup;
 GL_PROCS(LOAD)
#undef LOAD
 if(av_hwdevice_ctx_create(&device,AV_HWDEVICE_TYPE_VAAPI,node,NULL,0)<0)goto cleanup;
 AVHWDeviceContext *hardware=(AVHWDeviceContext *)device->data;
 VADisplay va=((AVVAAPIDeviceContext *)hardware->hwctx)->display;
 base=create_frame(device,WIDTH,HEIGHT,0);if(!base)goto cleanup;
 yb_native_playback_create_info info={0};info.version=2;info.egl_display=(uintptr_t)display;info.va_display=va;
 info.enhancement_scaler=(struct yb_vaapi_el_scale_config){EL_WIDTH,EL_HEIGHT,WIDTH,HEIGHT,YB_VPP_BILINEAR,1,VA_SOURCE_RANGE_FULL,
  VA_CHROMA_SITING_VERTICAL_TOP|VA_CHROMA_SITING_HORIZONTAL_LEFT,
  VA_CHROMA_SITING_VERTICAL_CENTER|VA_CHROMA_SITING_HORIZONTAL_LEFT};
 info.preparation=(yb_playback_shader){prep,strlen(prep)};info.composer=(yb_playback_shader){composer,strlen(composer)};info.ycc_expansion=(yb_playback_shader){ycc,strlen(ycc)};
 memcpy(info.guide_contract_id,association.preparation_id,32);memcpy(info.enhancement_scale_contract_id,association.enhancement_scale_id,32);memset(info.phase_contract_id,4,32);
 info.base_chroma_location=0;info.phase_filter=1;
 if(yb_native_playback_create(&info,&playback)!=YB_NATIVE_PLAYBACK_OK||!restored(display,context))goto cleanup;
 for(unsigned fixture=0;fixture<2;fixture++){
 el=create_frame(device,EL_WIDTH,EL_HEIGHT,(int)(512U+fixture));if(!el)goto cleanup;
 yb_native_playback_frame frame={0};frame.association=association;frame.base_frame=base;frame.enhancement_frame=el;
 frame.base_packet_timebase_num=frame.enhancement_packet_timebase_num=1;frame.base_packet_timebase_den=frame.enhancement_packet_timebase_den=1000000;
 frame.base_surface=(VASurfaceID)(uintptr_t)base->data[3];frame.enhancement_surface=(VASurfaceID)(uintptr_t)el->data[3];
 frame.base_width=WIDTH;frame.base_height=HEIGHT;frame.enhancement_width=EL_WIDTH;frame.enhancement_height=EL_HEIGHT;
 /* Deliberately copied bytes rather than side-data pointer identity. */
 frame.expanded_dovi_side_data=&metadata;frame.expanded_dovi_side_data_bytes=sizeof(metadata);
 if(!base->buf[0]||!el->buf[0])goto cleanup;
 if(fixture==1){
  const AVHWFramesContext *pool=(const AVHWFramesContext *)base->hw_frames_ctx->data;
  struct fixture_owner *owner=calloc(1,sizeof(*owner));if(!owner)goto cleanup;
  owner->storage=av_frame_clone(base);owner->display=va;owner->generation=9;
  owner->width=(uint32_t)pool->width;owner->height=(uint32_t)pool->height;
  if(!owner->storage){free(owner);goto cleanup;}
  owner_ref=av_buffer_create(NULL,0,owner_free,owner,0);
  if(!owner_ref){av_frame_free(&owner->storage);free(owner);goto cleanup;}
  snapshot=property_snapshot(base);if(!snapshot)goto cleanup;
  frame.base_frame=snapshot;frame.base_storage=YB_NATIVE_BASE_KODI_SURFACE;
  frame.kodi_base=(yb_native_kodi_base_surface){1,VA_FOURCC_P010,owner->width,owner->height,va,9,owner,owner_ref,owner_validate,owner_quarantine};
 }
 int base_refs=av_buffer_get_ref_count(base->buf[0]),el_refs=av_buffer_get_ref_count(el->buf[0]);
 /* Association rejection must leave decoded references untouched. */
 frame.association.el_pts++;
 if(yb_native_playback_submit(playback,&frame,UINT64_C(5000000000))!=YB_NATIVE_PLAYBACK_FALLBACK||!restored(display,context)||
    av_buffer_get_ref_count(base->buf[0])!=base_refs||av_buffer_get_ref_count(el->buf[0])!=el_refs)goto cleanup;
 frame.association=association;
 if(yb_native_playback_submit(playback,&frame,UINT64_C(5000000000))!=YB_NATIVE_PLAYBACK_OK||!restored(display,context))goto cleanup;
 if(av_buffer_get_ref_count(base->buf[0])!=base_refs+(fixture?0:1)||av_buffer_get_ref_count(el->buf[0])!=el_refs+1||
    (fixture && av_buffer_get_ref_count(owner_ref)!=2))goto cleanup;
 if(yb_native_playback_submit(playback,&frame,UINT64_C(5000000000))!=YB_NATIVE_PLAYBACK_PENDING||!restored(display,context))goto cleanup;
 yb_native_playback_output output={0};
 if(yb_native_playback_finish(playback,UINT64_C(5000000000),&output)!=YB_NATIVE_PLAYBACK_OK||!restored(display,context))goto cleanup;
 if(!output.texture||output.width!=WIDTH||output.height!=HEIGHT||memcmp(output.frame_id,association.frame_id,32))goto cleanup;
 gl.GenFramebuffers(1,&fbo);gl.BindFramebuffer(GL_FRAMEBUFFER,fbo);
 gl.FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,output.texture,0);
 if(gl.CheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)goto cleanup;
 gl.ReadPixels(0,0,WIDTH,HEIGHT,GL_RGBA,GL_FLOAT,actual);
 if(gl.GetError()!=GL_NO_ERROR||memcmp(expected[fixture],actual,sizeof(actual)))goto cleanup;
 gl.BindFramebuffer(GL_FRAMEBUFFER,0);gl.DeleteFramebuffers(1,&fbo);fbo=0;
 if(yb_native_playback_release(playback,UINT64_C(5000000000))!=YB_NATIVE_PLAYBACK_OK||!restored(display,context))goto cleanup;
 if(av_buffer_get_ref_count(base->buf[0])!=base_refs||av_buffer_get_ref_count(el->buf[0])!=el_refs)goto cleanup;
 if(fixture && av_buffer_get_ref_count(owner_ref)!=1)goto cleanup;
 av_frame_free(&snapshot);av_buffer_unref(&owner_ref);
 av_frame_free(&el);
 }
 if(yb_native_playback_destroy(&playback)!=YB_NATIVE_PLAYBACK_OK||playback||!restored(display,context))goto cleanup;
 if(owners_released!=1)goto cleanup;
 ok=1;
cleanup:
 if(playback&&yb_native_playback_destroy(&playback)!=YB_NATIVE_PLAYBACK_OK){
  (void)yb_native_playback_quarantine_retained(playback);return 0;
 }
 if(current&&!restored(display,context))return 0;
 if(current&&fbo&&gl.DeleteFramebuffers)gl.DeleteFramebuffers(1,&fbo);
 if(current&&!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))ok=0;
 if(context!=EGL_NO_CONTEXT&&!eglDestroyContext(display,context))ok=0;
 if(initialized&&!eglTerminate(display))ok=0;
 /* Quarantine retains decoder/device refs until this failing diagnostic exits.
  * Do not falsely assert device teardown: retained cloned AVFrames themselves
  * keep FFmpeg's VA device alive. No later hardware work is attempted here. */
 if(!playback){av_frame_free(&snapshot);av_buffer_unref(&owner_ref);av_frame_free(&base);av_frame_free(&el);av_buffer_unref(&device);}
 else ok=0;
 if(!eglReleaseThread())ok=0;
 if(fd>=0&&close(fd))ok=0;
 return ok;
}
int main(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"--validate")){
  int valid=prepare_cpu(0)&&prepare_cpu(1)&&guide_influenced_samples&&nonzero_residual_samples;
  printf("{\"schema\":\"yblod.native-playback-custom-context-synthetic-preflight.v1\",\"status\":\"%s\",\"gpu_attempted\":false,\"rgba_float_bits_prepared\":%u,\"guide_influenced_samples\":%u,\"nonzero_residual_samples\":%u}\n",valid?"validated":"failed",valid?2U*WIDTH*HEIGHT*4U:0U,guide_influenced_samples,nonzero_residual_samples);
  return valid?0:1;
 }
 if(argc!=5||!node_valid(argv[1]))return 2;
 if(!prepare_cpu(0)||!prepare_cpu(1)||!guide_influenced_samples||!nonzero_residual_samples)return 1;
 char *prep=shader_read(argv[2]),*composer=shader_read(argv[3]),*ycc=shader_read(argv[4]);
 if(!prep||!composer||!ycc){free(prep);free(composer);free(ycc);return 2;}
 int ok=execute(argv[1],prep,composer,ycc);free(prep);free(composer);free(ycc);
 printf("{\"schema\":\"yblod.native-playback-custom-context-synthetic-probe.v1\",\"complete\":%s,\"native_cpu_oracle_first\":true,\"rgba_float_bits_checked\":%u,\"guide_influenced_samples\":%u,\"nonzero_residual_samples\":%u,\"fixtures\":2,\"actual_ffmpeg_va_frames\":true,\"actual_expanded_dovi_metadata\":true,\"strict_clone_and_custom_owner_lifetime_checked\":%s,\"association_rejection_checked\":%s,\"context_restore_checks\":%u,\"input_scope\":\"public64x64BL32x32constantEL512and513; one strict HWFrames BL and one property-only custom BL owner; actual FFmpeg fixture owner, not Kodi pool; constant preservation, not scaler interpolation accuracy\"}\n",ok?"true":"false",ok?2U*WIDTH*HEIGHT*4U:0U,guide_influenced_samples,nonzero_residual_samples,ok?"true":"false",ok?"true":"false",ok?12U:0U);
 return ok?0:1;
}
