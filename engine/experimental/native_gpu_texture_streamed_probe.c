#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "native_scaled_surface.h"
#include "native_decoder_frame_bridge.h"
#include "native_mmr_composer.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Caller externally pins files, executable, libraries and cgroup. Offline arithmetic/transport
 * diagnostic, not playback FPS. No metadata JSON or fractional rounding. */
enum { CHUNK=65536, GPU_BATCH=262144 };
/* Surface and CPU arithmetic retain their 65,536-sample contracts. GPU
 * transfer/dispatch batches are assembled from bounded CPU-sized subchunks. */
static int suffix_offset(uint32_t batch_count,uint32_t cpu_count,uint32_t *offset)
{
 if(!offset||!cpu_count||cpu_count>CHUNK||batch_count>GPU_BATCH||batch_count<cpu_count)return 0;
 *offset=batch_count-cpu_count;return 1;
}
static int stable(const struct stat *a,const struct stat *b)
{
#ifdef __APPLE__
#define MT st_mtimespec
#define CT st_ctimespec
#else
#define MT st_mtim
#define CT st_ctim
#endif
 return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
  a->MT.tv_sec==b->MT.tv_sec && a->MT.tv_nsec==b->MT.tv_nsec &&
  a->CT.tv_sec==b->CT.tv_sec && a->CT.tv_nsec==b->CT.tv_nsec;
#undef MT
#undef CT
}
static void *load(const char *path,size_t bytes)
{
 static struct stat identities[6];static size_t loaded;
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK); struct stat a,b,c;
 if(fd<0)return NULL;
 void *p=NULL; size_t done=0;
 if(fstat(fd,&a)||!S_ISREG(a.st_mode)||a.st_size<0||(uint64_t)a.st_size!=bytes)goto end;
 if(loaded>=6)goto end;
 for(size_t i=0;i<loaded;i++)
  if(a.st_dev==identities[i].st_dev&&a.st_ino==identities[i].st_ino)goto end;
 p=malloc(bytes);if(!p)goto end;
 while(done<bytes){size_t n=bytes-done;if(n>65536)n=65536;
  ssize_t got=read(fd,(unsigned char *)p+done,n);
  if(got<0&&errno==EINTR)continue;
  if(got<=0)goto fail;
  done+=(size_t)got;
 }
 unsigned char extra;
 if(read(fd,&extra,1)!=0||fstat(fd,&b)||lstat(path,&c)||!S_ISREG(c.st_mode)||
    !stable(&a,&b)||!stable(&a,&c))goto fail;
 identities[loaded++]=a;goto end;
fail:free(p);p=NULL;
end:close(fd);return p;
}
static int whole(uint16_t *p,size_t count)
{
 unsigned char *raw=(unsigned char *)p;
 for(size_t i=0;i<count;i++){
  uint16_t v=(uint16_t)((uint16_t)raw[2*i]|((uint16_t)raw[2*i+1]<<8));
  if(v>1023)return 0;
  p[i]=v;
 }
 return 1;
}
static int number(const char *s,uint32_t *v)
{
 uint32_t n=0;if(!*s)return 0;
 for(;*s;s++){if(*s<'0'||*s>'9'||n>3840)return 0;n=n*10U+(uint32_t)(*s-'0');}
 if(!n||n>3840||(n&1U))return 0;
 *v=n;return 1;
}
#ifndef YB_GPU_PROBE_HOST_ONLY
static int ns(const struct timespec *a,const struct timespec *b,uint64_t *result)
{
 if(a->tv_sec<0 || b->tv_sec<a->tv_sec || a->tv_nsec<0 ||
    b->tv_nsec<0 || a->tv_nsec>=1000000000 || b->tv_nsec>=1000000000)return 0;
 uint64_t seconds=(uint64_t)b->tv_sec-(uint64_t)a->tv_sec;
 int64_t nanos=(int64_t)b->tv_nsec-(int64_t)a->tv_nsec;
 if(nanos<0){if(!seconds)return 0;seconds--;nanos+=1000000000;}
 if(seconds>UINT64_MAX/1000000000U)return 0;
 uint64_t base=seconds*1000000000U;
 if((uint64_t)nanos>UINT64_MAX-base)return 0;
 *result=base+(uint64_t)nanos;return 1;
}
#endif
/* Pure host-checkable normalized R16 and linear component-coordinate ABI. */
static int texture_recover_word(float value,uint16_t *word)
{
    if(!word || !(value>=0.0f && value<=1.0f))return 0;
    uint32_t recovered=(uint32_t)(value*65535.0f+0.5f);
    if(recovered>65535U)return 0;
    *word=(uint16_t)recovered;return 1;
}
static int texture_coordinate(uint32_t width,uint32_t height,uint32_t component,
    uint64_t start,uint32_t count,uint32_t local,uint32_t *x,uint32_t *y)
{
    if(!x||!y||x==y||!width||!height||width>3840||height>2160||
       ((width|height)&1U)||component>2||!count||count>262144||local>=count)return 0;
    uint64_t row=component?width/2U:width,rows=component?height/2U:height;
    uint64_t total=row*rows;
    if(start>total||count>total-start)return 0;
    uint64_t position=start+local;
    *x=(uint32_t)(position%row);*y=(uint32_t)(position/row);return 1;
}

struct stages { uint16_t *mapped,*out;int32_t *residual,*sum; };
struct workload {
 yb_integration_descriptor descriptor;
 yb_scaled_surface surface;
 void *blob;uint16_t *bl[4],*zero,*el;
 uint8_t frame[32],provenance[32];uint64_t counts[3];
};
struct measurement { uint64_t wall,cpu,preparation_wall,preparation_cpu; };
static int allocate_stages(struct stages *s)
{
 s->mapped=malloc(CHUNK*sizeof(*s->mapped));s->out=malloc(CHUNK*sizeof(*s->out));
 s->residual=malloc(CHUNK*sizeof(*s->residual));s->sum=malloc(CHUNK*sizeof(*s->sum));
 return s->mapped&&s->out&&s->residual&&s->sum;
}
static void free_stages(struct stages *s)
{ free(s->mapped);free(s->out);free(s->residual);free(s->sum); }
static int same_stages(const struct stages *a,const struct stages *b,uint32_t n)
{
 return !memcmp(a->mapped,b->mapped,(size_t)n*2) &&
        !memcmp(a->residual,b->residual,(size_t)n*4) &&
        !memcmp(a->sum,b->sum,(size_t)n*4) && !memcmp(a->out,b->out,(size_t)n*2);
}
static void save_stages(struct stages *a,const struct stages *b,uint32_t n)
{
 memcpy(a->mapped,b->mapped,(size_t)n*2);memcpy(a->residual,b->residual,(size_t)n*4);
 memcpy(a->sum,b->sum,(size_t)n*4);memcpy(a->out,b->out,(size_t)n*2);
}
static int completed(const yb_integration_completion *c,const struct workload *w)
{
 return c->kind==YB_ARITHMETIC_FRAME_COMPLETE && !c->diagnostic_queries &&
        c->counts[0]==w->counts[0] && c->counts[1]==w->counts[1] && c->counts[2]==w->counts[2];
}
static int create_mmr(yb_mmr_frame **mmr,const yb_integration_context *reference)
{
 return yb_mmr_frame_create(&reference->descriptor,&reference->mapping,
     reference->descriptor.enhancement_enabled ? reference->nlq : NULL,mmr);
}
static int dispatch(const struct workload *w,uint32_t c,uint64_t start,uint32_t count,
                    yb_integration_context *reference,yb_mmr_frame *mmr,struct stages *s)
{
 const uint16_t *y=c ? w->bl[3]+(size_t)start : w->bl[0]+(size_t)start;
 const uint16_t *cb=c ? w->bl[1]+(size_t)start : w->zero;
 const uint16_t *cr=c ? w->bl[2]+(size_t)start : w->zero;
 if(mmr)return yb_mmr_frame_process(mmr,w->frame,(int32_t)c,start,y,cb,cr,
     w->el,count,s->mapped,s->residual,s->sum,s->out);
 return yb_integration_integer(reference,w->frame,(int32_t)c,start,y,cb,cr,
     w->el,count,s->mapped,s->residual,s->sum,s->out);
}
static int verify_frame(const struct workload *w,struct stages *a,struct stages *b,
                        struct stages *golden,uint64_t *dispatches,uint32_t *last_count,
                        int routes[3],unsigned widths[2])
{
 yb_integration_context reference={0};yb_mmr_frame *mmr=NULL;
 yb_integration_completion rc={0},cc={0};int okay=0;
 if(yb_decoder_frame_bridge_init(&reference,&w->descriptor,w->blob,9216)||
    create_mmr(&mmr,&reference))goto end;
 for(int32_t c=0;c<3;c++){
  routes[c]=yb_mmr_frame_component_route(mmr,c);
  if(routes[c]!=0&&routes[c]!=1)goto end;
 }
 for(int32_t c=0;c<3;c++)for(int32_t i=0;i<YB_MAX_SEGMENTS;i++){
  int bits=yb_mmr_frame_segment_bits(mmr,c,i);
  if(bits<0)break;
  if(bits==64)widths[0]++;
  else if(bits==128)widths[1]++;
 }
 *dispatches=0;
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<w->counts[c];start+=CHUNK){
  uint32_t n=(uint32_t)(w->counts[c]-start);if(n>CHUNK)n=CHUNK;
  if(yb_scaled_surface_extract(&w->surface,w->frame,w->provenance,c,start,n,
       YB_SURFACE_EXACT_WHOLE_CODES,w->el)||dispatch(w,c,start,n,&reference,NULL,a)||
     dispatch(w,c,start,n,NULL,mmr,b)||!same_stages(a,b,n))goto end;
  ++*dispatches;*last_count=n;
 }
 if(yb_integration_finish(&reference,&rc)||yb_mmr_frame_finish(mmr,&cc)||
    !completed(&rc,w)||!completed(&cc,w))goto end;
 save_stages(golden,a,*last_count);okay=1;
end:yb_mmr_frame_destroy(mmr);yb_integration_reset(&reference);return okay;
}

#include "native_gpu_probe_fixture.h"
#ifndef YB_GPU_PROBE_HOST_ONLY
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <ctype.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

static int extension(const char *list,const char *name)
{
    if (!list) return 0;
    size_t size=strlen(name);
    for (const char *p=list;(p=strstr(p,name))!=NULL;p+=size)
        if ((p==list || p[-1]==' ') && (p[size]==' ' || !p[size])) return 1;
    return 0;
}
static void string_json(const char *text)
{
    if (!text) { fputs("null",stdout); return; }
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)text;*p;++p) {
        if (*p=='"' || *p=='\\') { putchar('\\'); putchar(*p); }
        else if (*p<32U || *p>=127U) printf("\\u%04x",(unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}
static int node_valid(const char *path)
{
    const char prefix[]="/dev/dri/renderD";
    if (strncmp(path,prefix,sizeof(prefix)-1)) return 0;
    const char *p=path+sizeof(prefix)-1;
    if (!*p) return 0;
    unsigned value=0;
    for (;*p;++p) {
        if (*p<'0' || *p>'9' || value>104857U) return 0;
        value=value*10U+(unsigned)(*p-'0');
    }
    return value>=128U && value<=1048575U;
}
static int software(const char *text)
{
    if (!text || strlen(text)>=4096) return 1;
    char lower[4096];
    for (size_t i=0;i<=strlen(text);++i) lower[i]=(char)tolower((unsigned char)text[i]);
    return strstr(lower,"llvmpipe") || strstr(lower,"softpipe") || strstr(lower,"software") || strstr(lower,"swrast");
}

struct gl_api {
    PFNGLGETSTRINGPROC GetString; PFNGLGETSTRINGIPROC GetStringi;
    PFNGLGETINTEGERVPROC GetIntegerv; PFNGLGETINTEGERI_VPROC GetIntegeri_v;
    PFNGLGETINTEGER64VPROC GetInteger64v; PFNGLGETERRORPROC GetError;
    PFNGLCREATESHADERPROC CreateShader; PFNGLSHADERSOURCEPROC ShaderSource;
    PFNGLCOMPILESHADERPROC CompileShader; PFNGLGETSHADERIVPROC GetShaderiv;
    PFNGLGETSHADERINFOLOGPROC GetShaderInfoLog; PFNGLDELETESHADERPROC DeleteShader;
    PFNGLCREATEPROGRAMPROC CreateProgram; PFNGLATTACHSHADERPROC AttachShader;
    PFNGLLINKPROGRAMPROC LinkProgram; PFNGLGETPROGRAMIVPROC GetProgramiv;
    PFNGLGETPROGRAMINFOLOGPROC GetProgramInfoLog; PFNGLDELETEPROGRAMPROC DeleteProgram;
    PFNGLUSEPROGRAMPROC UseProgram; PFNGLGENBUFFERSPROC GenBuffers;
    PFNGLBINDBUFFERPROC BindBuffer; PFNGLBUFFERDATAPROC BufferData;
    PFNGLBUFFERSUBDATAPROC BufferSubData; PFNGLGETBUFFERPARAMETERI64VPROC GetBufferParameteri64v;
    PFNGLBINDBUFFERBASEPROC BindBufferBase; PFNGLDELETEBUFFERSPROC DeleteBuffers;
    PFNGLDISPATCHCOMPUTEPROC DispatchCompute; PFNGLMEMORYBARRIERPROC MemoryBarrier;
    PFNGLFENCESYNCPROC FenceSync; PFNGLCLIENTWAITSYNCPROC ClientWaitSync;
    PFNGLDELETESYNCPROC DeleteSync; PFNGLGETBUFFERSUBDATAPROC GetBufferSubData;
    PFNGLGENTEXTURESPROC GenTextures; PFNGLACTIVETEXTUREPROC ActiveTexture;
    PFNGLBINDTEXTUREPROC BindTexture; PFNGLTEXPARAMETERIPROC TexParameteri;
    PFNGLTEXIMAGE2DPROC TexImage2D; PFNGLPIXELSTOREIPROC PixelStorei;
    PFNGLDELETETEXTURESPROC DeleteTextures; PFNGLUNIFORM3UIPROC Uniform3ui;
    PFNGLGETTEXLEVELPARAMETERIVPROC GetTexLevelParameteriv;
};
#define LOAD(field,type) do { gl.field=(type)eglGetProcAddress("gl" #field); if(!gl.field) goto cleanup; } while(0)

static char *read_shader(const char *path)
{
    int fd=open(path,O_RDONLY|O_NONBLOCK);
    if (fd<0) return NULL;
    struct stat info;
    if (fstat(fd,&info) || !S_ISREG(info.st_mode) || info.st_size<1 || info.st_size>65536) { close(fd); return NULL; }
    char *text=calloc((size_t)info.st_size+1,1);
    FILE *stream=fdopen(fd,"rb");
    if (!stream) { close(fd); free(text); return NULL; }
    int ok=text && fread(text,1,(size_t)info.st_size,stream)==(size_t)info.st_size && fgetc(stream)==EOF && !ferror(stream);
    struct stat after,path_after;
    if (fstat(fileno(stream),&after) || stat(path,&path_after) ||
        info.st_dev!=after.st_dev || info.st_ino!=after.st_ino || info.st_size!=after.st_size ||
        info.st_dev!=path_after.st_dev || info.st_ino!=path_after.st_ino || info.st_size!=path_after.st_size ||
        info.st_mtim.tv_sec!=after.st_mtim.tv_sec || info.st_mtim.tv_nsec!=after.st_mtim.tv_nsec ||
        info.st_ctim.tv_sec!=after.st_ctim.tv_sec || info.st_ctim.tv_nsec!=after.st_ctim.tv_nsec ||
        info.st_mtim.tv_sec!=path_after.st_mtim.tv_sec || info.st_mtim.tv_nsec!=path_after.st_mtim.tv_nsec ||
        info.st_ctim.tv_sec!=path_after.st_ctim.tv_sec || info.st_ctim.tv_nsec!=path_after.st_ctim.tv_nsec) ok=0;
    if (fclose(stream)) ok=0;
    if (!ok || memchr(text,0,(size_t)info.st_size)) { free(text); return NULL; }
    return text;
}

static int gpu_run(const char *node,const char *shader_path,const struct workload *w,struct yb_probe_fixture *f,struct stages *scratch,const struct stages *golden,uint32_t last_count)
{
    struct timespec cold_begin,cold_end,teardown_begin,teardown_end;
    struct measurement times[3]={{0}},dispatch_times[3]={{0}};
    uint64_t preload_wait_ns[3]={0}; uint64_t cold_ns=0,teardown_ns=0,verified=0,oracle_dispatches=0,values=0;
    uint32_t final_gpu_count=0;
    uint64_t texture_setup_wall=0,texture_setup_cpu=0;
    const uint32_t width=w->descriptor.width,height=w->descriptor.height;
    uint32_t coordinate_x=0,coordinate_y=0;
    if(!texture_coordinate(width,height,0,0,1,0,&coordinate_x,&coordinate_y))return 0;
    if(clock_gettime(CLOCK_MONOTONIC,&cold_begin)) return 0;
    f->count=GPU_BATCH;
    int ok=0, fd=-1, initialized=0, current=0, bound=0;
    const char *operation="preflight";
    EGLDisplay display=EGL_NO_DISPLAY; EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[3]={0,0,0},textures[5]={0,0,0,0,0}; GLsync fence=NULL;
    struct gl_api gl={0};
    char *source=NULL;
    _Static_assert(sizeof(uint32_t)==4 && sizeof(int32_t)==4 && sizeof(int64_t)==8,"SSBO scalar widths");
    const size_t wire_bytes=(size_t)f->count*4*sizeof(int32_t);
    int32_t *actual=calloc((size_t)f->count*4,sizeof(*actual));
    uint16_t *packed_y=NULL,*packed_uv=NULL;
    GLenum observed_gl_error=GL_NO_ERROR;
    EGLint observed_egl_error=EGL_SUCCESS;
    struct stat requested;
    const uint16_t endian=1;
    if (!actual || *(const unsigned char *)&endian!=1 || !node_valid(node)) goto cleanup;
    for(size_t i=0;i<(size_t)f->count*4;++i) actual[i]=INT32_MIN;
    source=read_shader(shader_path);
    if (!source) goto cleanup;
    operation="requested render-node open";
    fd=open(node,O_RDWR|O_CLOEXEC);
    if (fd<0 || fstat(fd,&requested) || !S_ISCHR(requested.st_mode)) goto cleanup;
    operation="EGL device capabilities";
    const char *client=eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    if ((observed_egl_error=eglGetError())!=EGL_SUCCESS || !extension(client,"EGL_EXT_platform_device") ||
        !(extension(client,"EGL_EXT_device_base") || (extension(client,"EGL_EXT_device_enumeration") && extension(client,"EGL_EXT_device_query")))) goto cleanup;
    PFNEGLQUERYDEVICESEXTPROC query_devices=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC device_string=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    PFNEGLQUERYDISPLAYATTRIBEXTPROC display_attribute=(PFNEGLQUERYDISPLAYATTRIBEXTPROC)eglGetProcAddress("eglQueryDisplayAttribEXT");
    if (!query_devices || !device_string || !platform_display || !display_attribute) goto cleanup;
    EGLint count=0,returned=0; EGLDeviceEXT listed[32],selected=EGL_NO_DEVICE_EXT;
    if (!query_devices(0,NULL,&count) || count<1 || count>32 || !query_devices(count,listed,&returned) || count!=returned) goto cleanup;
    unsigned matches=0;
    for (EGLint i=0;i<count;++i) {
        const char *extensions=device_string(listed[i],EGL_EXTENSIONS);
        if (eglGetError()!=EGL_SUCCESS || !extension(extensions,"EGL_EXT_device_drm_render_node") || extension(extensions,"EGL_MESA_device_software")) continue;
        const char *path=device_string(listed[i],EGL_DRM_RENDER_NODE_FILE_EXT);
        EGLint error=eglGetError(); struct stat candidate;
        if (error==EGL_SUCCESS && path && !stat(path,&candidate) && S_ISCHR(candidate.st_mode) && candidate.st_rdev==requested.st_rdev) { ++matches; selected=listed[i]; }
    }
    if (matches!=1) goto cleanup;
    operation="EGL display association";
    display=platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);
    EGLint egl_major=0,egl_minor=0;
    if (display==EGL_NO_DISPLAY || !eglInitialize(display,&egl_major,&egl_minor)) goto cleanup;
    initialized=1; EGLAttrib device=0;
    if (!display_attribute(display,EGL_DEVICE_EXT,&device) || (EGLDeviceEXT)device!=selected) goto cleanup;
    bound=1;
    const char *display_extensions=eglQueryString(display,EGL_EXTENSIONS);
    if ((observed_egl_error=eglGetError())!=EGL_SUCCESS || !extension(display_extensions,"EGL_KHR_surfaceless_context") ||
        !((egl_major>1 || (egl_major==1 && egl_minor>=5)) || extension(display_extensions,"EGL_KHR_create_context"))) goto cleanup;
    operation="desktop GL4.3 core context";
    if (!eglBindAPI(EGL_OPENGL_API)) goto cleanup;
    const EGLint config_attributes[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config; EGLint configs=0;
    if (!eglChooseConfig(display,config_attributes,&config,1,&configs) || configs!=1) goto cleanup;
    context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    if (context==EGL_NO_CONTEXT || !eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) goto cleanup;
    current=1; operation="GL entrypoints";
    LOAD(GetString,PFNGLGETSTRINGPROC); LOAD(GetStringi,PFNGLGETSTRINGIPROC);
    LOAD(GetIntegerv,PFNGLGETINTEGERVPROC); LOAD(GetIntegeri_v,PFNGLGETINTEGERI_VPROC);
    LOAD(GetInteger64v,PFNGLGETINTEGER64VPROC); LOAD(GetError,PFNGLGETERRORPROC);
    LOAD(CreateShader,PFNGLCREATESHADERPROC); LOAD(ShaderSource,PFNGLSHADERSOURCEPROC);
    LOAD(CompileShader,PFNGLCOMPILESHADERPROC); LOAD(GetShaderiv,PFNGLGETSHADERIVPROC);
    LOAD(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC); LOAD(DeleteShader,PFNGLDELETESHADERPROC);
    LOAD(CreateProgram,PFNGLCREATEPROGRAMPROC); LOAD(AttachShader,PFNGLATTACHSHADERPROC);
    LOAD(LinkProgram,PFNGLLINKPROGRAMPROC); LOAD(GetProgramiv,PFNGLGETPROGRAMIVPROC);
    LOAD(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC); LOAD(DeleteProgram,PFNGLDELETEPROGRAMPROC);
    LOAD(UseProgram,PFNGLUSEPROGRAMPROC); LOAD(GenBuffers,PFNGLGENBUFFERSPROC);
    LOAD(BindBuffer,PFNGLBINDBUFFERPROC); LOAD(BufferData,PFNGLBUFFERDATAPROC);
    LOAD(BufferSubData,PFNGLBUFFERSUBDATAPROC); LOAD(GetBufferParameteri64v,PFNGLGETBUFFERPARAMETERI64VPROC);
    LOAD(BindBufferBase,PFNGLBINDBUFFERBASEPROC); LOAD(DeleteBuffers,PFNGLDELETEBUFFERSPROC);
    LOAD(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC); LOAD(MemoryBarrier,PFNGLMEMORYBARRIERPROC);
    LOAD(FenceSync,PFNGLFENCESYNCPROC); LOAD(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC);
    LOAD(DeleteSync,PFNGLDELETESYNCPROC); LOAD(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC);
    LOAD(GenTextures,PFNGLGENTEXTURESPROC); LOAD(ActiveTexture,PFNGLACTIVETEXTUREPROC);
    LOAD(BindTexture,PFNGLBINDTEXTUREPROC); LOAD(TexParameteri,PFNGLTEXPARAMETERIPROC);
    LOAD(TexImage2D,PFNGLTEXIMAGE2DPROC); LOAD(PixelStorei,PFNGLPIXELSTOREIPROC);
    LOAD(DeleteTextures,PFNGLDELETETEXTURESPROC); LOAD(Uniform3ui,PFNGLUNIFORM3UIPROC);
    LOAD(GetTexLevelParameteriv,PFNGLGETTEXLEVELPARAMETERIVPROC);
    operation="GL version/renderer/int64 checks";
    const char *renderer=(const char *)gl.GetString(GL_RENDERER), *version=(const char *)gl.GetString(GL_VERSION);
    fputs(",\"renderer\":",stdout); string_json(renderer); fputs(",\"gl_version\":",stdout); string_json(version);
    GLint major=0,minor=0,num_extensions=0; gl.GetIntegerv(GL_MAJOR_VERSION,&major); gl.GetIntegerv(GL_MINOR_VERSION,&minor); gl.GetIntegerv(GL_NUM_EXTENSIONS,&num_extensions);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || software(renderer) || major<4 || (major==4 && minor<3) || num_extensions<0 || num_extensions>8192) goto cleanup;
    int int64_supported=0;
    for (GLint i=0;i<num_extensions;++i) { const char *name=(const char *)gl.GetStringi(GL_EXTENSIONS,(GLuint)i); if(name && !strcmp(name,"GL_ARB_gpu_shader_int64")) int64_supported=1; }
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !int64_supported) goto cleanup;
    operation="compute limits";
    GLint invocations=0,size=0,groups=0,blocks=0,bindings=0; GLint64 block_size=0;
    gl.GetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,&invocations); gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,0,&size);
    gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,0,&groups); gl.GetIntegerv(GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS,&blocks);
    gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&bindings); gl.GetInteger64v(GL_MAX_SHADER_STORAGE_BLOCK_SIZE,&block_size);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || invocations<64 || size<64 || groups<(GLint)((f->count+63)/64) || blocks<3 || bindings<3 || block_size<(GLint64)wire_bytes || block_size<(GLint64)(YB_PROBE_METADATA_WORDS*sizeof(int64_t))) goto cleanup;
    operation="shader compile";
    shader=gl.CreateShader(GL_COMPUTE_SHADER); if (!shader) goto cleanup;
    const GLchar *source_pointer=source; gl.ShaderSource(shader,1,&source_pointer,NULL); gl.CompileShader(shader);
    GLint compiled=0; gl.GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    char log[8192]={0}; GLsizei log_length=0; gl.GetShaderInfoLog(shader,(GLsizei)sizeof(log)-1,&log_length,log);
    fputs(",\"shader_log\":",stdout); string_json(log);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !compiled) goto cleanup;
    operation="program link";
    program=gl.CreateProgram(); if(!program) goto cleanup;
    gl.AttachShader(program,shader); gl.LinkProgram(program);
    GLint linked=0; gl.GetProgramiv(program,GL_LINK_STATUS,&linked); memset(log,0,sizeof(log));
    gl.GetProgramInfoLog(program,(GLsizei)sizeof(log)-1,&log_length,log); fputs(",\"link_log\":",stdout); string_json(log);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !linked) goto cleanup;
    operation="linked work-group dimensions";
    GLint linked_group_size[3]={0,0,0};
    gl.GetProgramiv(program,GL_COMPUTE_WORK_GROUP_SIZE,linked_group_size);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || linked_group_size[0]!=64 ||
        linked_group_size[1]!=1 || linked_group_size[2]!=1) goto cleanup;
    GLint texture_limit=0,texture_units=0;
    gl.GetIntegerv(GL_MAX_TEXTURE_SIZE,&texture_limit);
    gl.GetIntegerv(GL_MAX_COMPUTE_TEXTURE_IMAGE_UNITS,&texture_units);
    if(gl.GetError()!=GL_NO_ERROR||texture_limit<(GLint)width||texture_limit<(GLint)height||texture_units<5)goto cleanup;
    operation="private metadata and output SSBO allocation";
    int64_t metadata[YB_PROBE_METADATA_WORDS]; yb_probe_metadata(f,metadata);
    gl.GenBuffers(3,buffers);
    for (unsigned i=0;i<3;++i) if(!buffers[i]) goto cleanup;
    for (GLuint i=0;i<3;++i) {
        if(i==1)continue; /* No expanded sample SSBO exists in this runner. */
        gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[i]);
        GLsizeiptr bytes=i==0 ? (GLsizeiptr)sizeof(metadata) : (GLsizeiptr)wire_bytes;
        const void *data=i==0 ? (const void *)metadata : (const void *)actual;
        gl.BufferData(GL_SHADER_STORAGE_BUFFER,bytes,data,GL_DYNAMIC_COPY); gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,i,buffers[i]);
        GLint64 actual_size=0;gl.GetBufferParameteri64v(GL_SHADER_STORAGE_BUFFER,GL_BUFFER_SIZE,&actual_size);
        if(actual_size!=(GLint64)bytes)goto cleanup;
    }
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR) goto cleanup;

    /* This checkpoint uploads raw normalized planes once. It is NOT a VA
     * import/zero-copy test. Native BL fixture planes are packed to P010 once;
     * guide codes remain explicit, with no resampling or filtering policy. */
    struct timespec texture_begin,texture_begin_cpu,texture_end,texture_end_cpu;
    if(clock_gettime(CLOCK_MONOTONIC,&texture_begin)||
       clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&texture_begin_cpu))goto cleanup;
    operation="normalized texture preparation/upload";
    packed_y=malloc((size_t)width*height*2);
    packed_uv=malloc((size_t)width*height);
    if(!packed_y||!packed_uv)goto cleanup;
    for(uint64_t i=0;i<w->counts[0];i++)packed_y[i]=(uint16_t)(w->bl[0][i]<<6);
    for(uint64_t i=0;i<w->counts[1];i++){
        packed_uv[2*i]=(uint16_t)(w->bl[1][i]<<6);
        packed_uv[2*i+1]=(uint16_t)(w->bl[2][i]<<6);
    }
    const void *texture_data[5]={packed_y,packed_uv,w->bl[3],
        w->surface.allocation+(size_t)w->surface.y_offset,
        w->surface.allocation+(size_t)w->surface.uv_offset};
    gl.GenTextures(5,textures);
    for(unsigned slot=0;slot<5;slot++){
        int pair=slot==1||slot==4;
        int half=slot==1||slot==2||slot==4;
        GLsizei tw=(GLsizei)(half?width/2U:width),th=(GLsizei)(half?height/2U:height);
        if(!textures[slot])goto cleanup;
        gl.ActiveTexture(GL_TEXTURE0+slot);gl.BindTexture(GL_TEXTURE_2D,textures[slot]);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
        gl.PixelStorei(GL_UNPACK_ALIGNMENT,2);
        GLint row_length=slot==3?(GLint)(w->surface.y_stride/2U):
                         slot==4?(GLint)(w->surface.uv_stride/4U):0;
        gl.PixelStorei(GL_UNPACK_ROW_LENGTH,row_length);
        gl.TexImage2D(GL_TEXTURE_2D,0,pair?GL_RG16:GL_R16,tw,th,0,
                     pair?GL_RG:GL_RED,GL_UNSIGNED_SHORT,texture_data[slot]);
        GLint aw=0,ah=0,format=0;
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&aw);
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&ah);
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
        if(gl.GetError()!=GL_NO_ERROR||aw!=tw||ah!=th||format!=(pair?GL_RG16:GL_R16))goto cleanup;
    }
    gl.PixelStorei(GL_UNPACK_ROW_LENGTH,0);gl.PixelStorei(GL_UNPACK_ALIGNMENT,4);
    fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if(gl.GetError()!=GL_NO_ERROR||!fence)goto cleanup;
    GLenum texture_wait=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(5000000000));
    if(gl.GetError()!=GL_NO_ERROR||(texture_wait!=GL_ALREADY_SIGNALED&&texture_wait!=GL_CONDITION_SATISFIED))goto cleanup;
    gl.DeleteSync(fence);fence=NULL;
    free(packed_y);packed_y=NULL;free(packed_uv);packed_uv=NULL;
    if(clock_gettime(CLOCK_MONOTONIC,&texture_end)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&texture_end_cpu)||
       !ns(&texture_begin,&texture_end,&texture_setup_wall)||
       !ns(&texture_begin_cpu,&texture_end_cpu,&texture_setup_cpu))goto cleanup;

    if(clock_gettime(CLOCK_MONOTONIC,&cold_end)||!ns(&cold_begin,&cold_end,&cold_ns))goto cleanup;
    /* Pass zero is the complete untimed GPU/CPU gate; pass one warms the
     * persistent program and pass two through four are measured. */
    for(unsigned pass=0;pass<5;pass++){
        yb_integration_context reference={0};
        yb_integration_completion completion={0};
        struct timespec begin,begin_cpu,finish,finish_cpu;
        int pass_ok=0;
        uint64_t counts[3]={0,0,0};
        if(pass>=2 && (clock_gettime(CLOCK_MONOTONIC,&begin)||
                         clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&begin_cpu)))goto cleanup;
        if(pass==0 && yb_decoder_frame_bridge_init(&reference,&w->descriptor,w->blob,9216))goto cleanup;
        for(uint32_t c=0;c<3;c++){
            f->component=(int32_t)c;f->nlq=((yb_dovi_integer_instructions *)w->blob)->nlq[c];
            for(uint64_t start=0;start<w->counts[c];start+=GPU_BATCH){
                uint32_t n=(uint32_t)(w->counts[c]-start);if(n>GPU_BATCH)n=GPU_BATCH;
                f->count=n;final_gpu_count=n;
                if(!texture_coordinate(width,height,c,start,n,0,&coordinate_x,&coordinate_y))goto pass_cleanup;
                if(pass==0)for(uint32_t i=0;i<n*4U;i++)actual[i]=INT32_MIN;
                yb_probe_metadata(f,metadata);
                operation="chunk metadata upload and texture coordinate";
                gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[0]);
                gl.BufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(metadata),metadata);
                gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,0,buffers[0]);
                if(pass==0){
                    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[2]);
                    gl.BufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)((size_t)n*16),actual);
                }
                gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,2,buffers[2]);
                gl.UseProgram(program);
                gl.Uniform3ui(0,width,height,(GLuint)start);
                if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto pass_cleanup;
                /* Upload and compute remain ordered GL commands. One finite
                 * completion wait after dispatch covers both operations.
                 * No preload fence, unsynchronized mapping or reordered upload. */
                struct timespec dispatch_begin,dispatch_cpu_begin;
                if(pass>=2 && (clock_gettime(CLOCK_MONOTONIC,&dispatch_begin)||
                   clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&dispatch_cpu_begin)))goto pass_cleanup;
                operation="bounded compute dispatch";
                gl.UseProgram(program);gl.DispatchCompute((n+63)/64,1,1);
                gl.MemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
                fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
                if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||!fence)goto pass_cleanup;
                GLenum waited=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(5000000000));
                if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||
                   (waited!=GL_ALREADY_SIGNALED&&waited!=GL_CONDITION_SATISFIED))goto pass_cleanup;
                gl.DeleteSync(fence);fence=NULL;
                if(pass>=2){
                    struct timespec dispatch_end,dispatch_cpu_end;uint64_t wall=0,cpu=0;
                    if(clock_gettime(CLOCK_MONOTONIC,&dispatch_end)||
                       clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&dispatch_cpu_end)||
                       !ns(&dispatch_begin,&dispatch_end,&wall)||
                       !ns(&dispatch_cpu_begin,&dispatch_cpu_end,&cpu)||
                       wall>UINT64_MAX-dispatch_times[pass-2].wall||
                       cpu>UINT64_MAX-dispatch_times[pass-2].cpu)goto pass_cleanup;
                    dispatch_times[pass-2].wall+=wall;dispatch_times[pass-2].cpu+=cpu;
                }
                if(pass==0){
                    operation="complete gate readback";
                    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[2]);
                    gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)((size_t)n*16),actual);
                    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto pass_cleanup;
                }else if(c==2 && start+n==w->counts[c]){
                    /* Only final suffix observability, not timed full equality.
                     * Every batch still has a finite completion wait. */
                    uint32_t tail=0;
                    if(!suffix_offset(n,last_count,&tail))goto pass_cleanup;
                    operation="final suffix readback";
                    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[2]);
                    gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,(GLintptr)((size_t)tail*16),
                        (GLsizeiptr)((size_t)last_count*16),actual+(size_t)tail*4);
                    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto pass_cleanup;
                }
                if(pass==0){
                    operation="complete four stage oracle comparison";
                    for(uint32_t offset=0;offset<n;offset+=CHUNK){
                        uint32_t subcount=n-offset;if(subcount>CHUNK)subcount=CHUNK;
                        uint64_t substart=start+offset;
                        if(yb_scaled_surface_extract(&w->surface,w->frame,w->provenance,c,substart,subcount,
                             YB_SURFACE_EXACT_WHOLE_CODES,w->el)||
                           dispatch(w,c,substart,subcount,&reference,NULL,scratch))goto pass_cleanup;
                        for(uint32_t i=0;i<subcount;i++){
                            size_t index=(size_t)offset+i;
                            if(actual[4*index]!=scratch->mapped[i]||actual[4*index+1]!=scratch->residual[i]||
                               actual[4*index+2]!=scratch->sum[i]||actual[4*index+3]!=scratch->out[i])goto pass_cleanup;
                        }
                        oracle_dispatches++;
                    }
                    verified++;values+=(uint64_t)n*4;
                }
                counts[c]+=n;
            }
        }
        if(memcmp(counts,w->counts,sizeof(counts)))goto pass_cleanup;
        if(pass==0 && (yb_integration_finish(&reference,&completion)||!completed(&completion,w)))goto pass_cleanup;
        if(pass>=2){
            if(clock_gettime(CLOCK_MONOTONIC,&finish)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&finish_cpu)||
               !ns(&begin,&finish,&times[pass-2].wall)||!ns(&begin_cpu,&finish_cpu,&times[pass-2].cpu))goto pass_cleanup;
        }
        /* Observability only, outside timer: every stage of the final CPU-sized suffix of the last GPU batch.
         * Full GPU frame equality was established by pass zero above. */
        uint32_t suffix=0;
        if(!suffix_offset(final_gpu_count,last_count,&suffix))goto pass_cleanup;
        for(uint32_t i=0;i<last_count;i++){
            size_t index=(size_t)suffix+i;
            if(actual[4*index]!=golden->mapped[i]||actual[4*index+1]!=golden->residual[i]||
               actual[4*index+2]!=golden->sum[i]||actual[4*index+3]!=golden->out[i])goto pass_cleanup;
        }
        pass_ok=1;
pass_cleanup:
        yb_integration_reset(&reference);
        if(!pass_ok)goto cleanup;
    }
    printf(",\"warm_preload_waits_per_batch\":0,\"warm_completion_waits_per_batch\":1,\"warm_output_sentinel_uploads\":0,\"warm_readbacks_per_pass\":1,\"warm_readback_bytes\":%" PRIu64,(uint64_t)last_count*16U);
    printf(",\"texture_input_abi\":\"normalized-R16-RG16-P010-plus-explicit-native-guide\",\"texture_input_uploaded_checkpoint\":true,\"vaapi_zero_copy_import\":false,\"cpu_expanded_sample_ssbo\":false,\"input_planes_resident\":true,\"warm_input_plane_uploads\":0,\"resident_texture_setup_wall_ns\":%" PRIu64 ",\"resident_texture_setup_cpu_ns\":%" PRIu64,texture_setup_wall,texture_setup_cpu);
    ok=1;
cleanup:
    int teardown_clock=clock_gettime(CLOCK_MONOTONIC,&teardown_begin)==0;
    if(!ok) { fputs(",\"failure_operation\":",stdout); string_json(operation); }
    int cleanup_ok=1;
    EGLint final_egl_error=eglGetError();
    if(final_egl_error!=EGL_SUCCESS) observed_egl_error=final_egl_error;
    if(current && gl.GetError) { GLenum pending=gl.GetError(); if(pending!=GL_NO_ERROR) observed_gl_error=pending; }
    if(current) {
        if(fence && gl.DeleteSync) gl.DeleteSync(fence);
        if(gl.DeleteTextures) gl.DeleteTextures(5,textures);
        if(gl.DeleteBuffers) gl.DeleteBuffers(3,buffers);
        if(program && gl.DeleteProgram) gl.DeleteProgram(program);
        if(shader && gl.DeleteShader) gl.DeleteShader(shader);
        if(gl.GetError && gl.GetError()!=GL_NO_ERROR) cleanup_ok=0;
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)) cleanup_ok=0;
    }
    if(context!=EGL_NO_CONTEXT && !eglDestroyContext(display,context)) cleanup_ok=0;
    if(initialized && !eglTerminate(display)) cleanup_ok=0;
    if(!eglReleaseThread()) cleanup_ok=0;
    if(fd>=0 && close(fd)) cleanup_ok=0;
    free(actual);free(packed_y);free(packed_uv);free(source);
    printf(",\"device_binding_verified\":%s,\"observed_gl_error\":%u,\"observed_egl_error\":%u,\"cleanup_succeeded\":%s",
           bound ? "true" : "false",(unsigned)observed_gl_error,(unsigned)observed_egl_error,cleanup_ok ? "true" : "false");
    if(!teardown_clock||clock_gettime(CLOCK_MONOTONIC,&teardown_end)||!ns(&teardown_begin,&teardown_end,&teardown_ns))cleanup_ok=0;
    if(ok&&cleanup_ok) printf(",\"full_frame_gpu_exact\":true,\"gpu_verified_dispatches\":%" PRIu64 ",\"gpu_oracle_dispatches\":%" PRIu64 ",\"gpu_verified_stage_values\":%" PRIu64 ",\"cold_setup_wall_ns\":%" PRIu64 ",\"teardown_wall_ns\":%" PRIu64 ",\"warmups\":1,\"wall_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"cpu_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",verified,oracle_dispatches,values,cold_ns,teardown_ns,times[0].wall,times[1].wall,times[2].wall,times[0].cpu,times[1].cpu,times[2].cpu);
    if(ok&&cleanup_ok) printf(",\"preloaded_chunk_dispatch_measurement\":false,\"whole_frame_resident\":false,\"dispatch_timing_is_device_kernel_time\":false,\"dispatch_timing_scope\":\"sum of dispatch, barrier, fence and host wait; may include pending upload work; excludes preparation, upload API calls and readback\",\"preload_wait_wall_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"dispatch_wall_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"dispatch_cpu_ns\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",preload_wait_ns[0],preload_wait_ns[1],preload_wait_ns[2],dispatch_times[0].wall,dispatch_times[1].wall,dispatch_times[2].wall,dispatch_times[0].cpu,dispatch_times[1].cpu,dispatch_times[2].cpu);
    return ok && cleanup_ok;
}
#endif
int main(int argc,char **argv)
{
 uint32_t w,h;int status=1,reported=0;
 uint16_t recovered_word=0;
 if(!texture_recover_word(0.0f,&recovered_word))return 2;
 uint32_t tx=0,ty=0;
 if(!texture_coordinate(2,2,0,0,1,0,&tx,&ty))return 2;
 if(argc!=11){fprintf(stderr,"usage: probe NODE SHADER width height instructions BL-Y BL-Cb BL-Cr guide P010\n");return 2;}
 const char *node=argv[1],*shader_path=argv[2];int validate=!strcmp(node,"--validate");
 argc-=2;argv+=2;
 struct yb_probe_fixture fixture={0};
 if(yb_mmr_abi_version()!=1 || !yb_mmr_sizeof_plan() || !yb_mmr_sizeof_frame() ||
    yb_scaled_surface_abi_version()!=1 ||
    yb_scaled_surface_sizeof_descriptor()!=sizeof(yb_scaled_surface) ||
    yb_decoder_frame_bridge_abi_version()!=1 ||
    yb_decoder_frame_bridge_sizeof_instructions()!=sizeof(yb_dovi_integer_instructions) ||
    sizeof(yb_dovi_integer_instructions)!=9216 || yb_integration_abi_version()!=1 ||
    yb_integration_sizeof_descriptor()!=sizeof(yb_integration_descriptor) ||
    yb_integration_sizeof_context()!=sizeof(yb_integration_context) ||
    yb_integration_sizeof_completion()!=sizeof(yb_integration_completion) ||
    yb_abi_version()!=1 || yb_sizeof_mapping_config()!=sizeof(struct yb_mapping_config) ||
    yb_sizeof_nlq_config()!=sizeof(struct yb_nlq_config) ||
    yb_sizeof_component_mapping()!=sizeof(struct yb_component_mapping) ||
    yb_sizeof_segment()!=sizeof(struct yb_segment))return 1;
 if(argc!=9||!number(argv[1],&w)||!number(argv[2],&h)||h>2160){
  fprintf(stderr,"usage: benchmark width height instructions BL-Y BL-Cb BL-Cr guide P010\n");return 1;
 }
 size_t ycount=(size_t)w*h,ccount=ycount/4;
 if(ycount*9U+9216U>128U*1024U*1024U)return 1;
 void *blob=load(argv[3],9216);
 uint16_t *bl[4]={load(argv[4],ycount*2),load(argv[5],ccount*2),
                 load(argv[6],ccount*2),load(argv[7],ccount*2)};
 unsigned char *pixels=load(argv[8],ycount*3);
 uint16_t *el=malloc(CHUNK*sizeof(*el));
 struct stages a={0},b={0},golden={0};
 uint16_t *zero=calloc(CHUNK,sizeof(*zero));
 if(!blob||!pixels||!el||!zero||!allocate_stages(&a)||!allocate_stages(&b)||
    !allocate_stages(&golden))goto end;
 for(int i=0;i<4;i++)if(!bl[i]||!whole(bl[i],i==0?ycount:ccount))goto end;
 yb_dovi_integer_instructions instructions;
 if(sizeof(instructions)!=9216)goto end;
 memcpy(&instructions,blob,sizeof(instructions));
 if(instructions.residual_enabled!=1||instructions.mapping.bit_depth!=10||
    instructions.version!=1)goto end;
 for(int i=0;i<3;i++)if(instructions.nlq[i].bit_depth!=10)goto end;
 if(yb_validate_mapping(&instructions.mapping))goto end;
 fixture.mapping=instructions.mapping;fixture.enabled=1;fixture.output_depth=instructions.output_depth;
 if(yb_gpu_check_mapping_width(&instructions.mapping,&fixture.width))goto end;
 for(int i=0;i<instructions.mapping.components[0].pivot_count-1;i++)
  if(instructions.mapping.components[0].segments[i].method!=YB_POLYNOMIAL)goto end;
 yb_integration_descriptor d={0};d.version=1;d.input_kind=YB_INPUT_WHOLE_CODES;
 d.width=w;d.height=h;d.output_depth=instructions.output_depth;d.enhancement_enabled=1;
 d.frame_id[0]=1;d.provenance_id[0]=2;
 uint8_t frame[32]={1},provenance[32]={2};
 yb_scaled_surface surface={0};surface.version=1;surface.format=YB_SURFACE_NATIVE10_Q6;
 surface.width=w;surface.height=h;surface.coherent_ready=1;surface.allocation=pixels;
 surface.allocation_bytes=ycount*3;surface.uv_offset=ycount*2;
 surface.y_stride=(uint64_t)w*2;surface.uv_stride=(uint64_t)w*2;
 memcpy(surface.frame_id,frame,32);memcpy(surface.provenance_id,provenance,32);
 uint64_t counts[3]={ycount,ccount,ccount};
 for(uint32_t c=0;c<3;c++)for(uint64_t start=0;start<counts[c];start+=CHUNK){
  uint32_t count=(uint32_t)(counts[c]-start);if(count>CHUNK)count=CHUNK;
  if(yb_scaled_surface_extract(&surface,frame,provenance,c,start,count,
                              YB_SURFACE_EXACT_WHOLE_CODES,el))goto end;
 }
 yb_integration_context validated_bridge={0};
 if(yb_decoder_frame_bridge_init(&validated_bridge,&d,blob,9216))goto end;
 yb_integration_reset(&validated_bridge);
 if(!fixture.width.supported){
  printf("{\"schema\":\"yblod.native-gpu-texture-streamed-probe.v1\",\"status\":\"unsupported\",\"gpu_attempted\":false,\"cpu_full_frame_gate\":false,\"full_frame_gpu_exact\":false,\"gpu_verified_dispatches\":0,\"gpu_oracle_dispatches\":0,\"gpu_verified_stage_values\":0}\n");reported=1;status=3;goto end;
 }
 struct workload work={0};work.descriptor=d;work.surface=surface;work.blob=blob;
 for(int i=0;i<4;i++)work.bl[i]=bl[i];
 work.zero=zero;work.el=el;memcpy(work.frame,frame,32);memcpy(work.provenance,provenance,32);
 memcpy(work.counts,counts,sizeof(counts));
 uint64_t dispatches=0;uint32_t last_count=0;int routes[3]={0};unsigned widths[2]={0};
 if(!verify_frame(&work,&a,&b,&golden,&dispatches,&last_count,routes,widths))goto end;

 printf("{\"schema\":\"yblod.native-gpu-texture-streamed-probe.v1\",\"gpu_attempted\":%s,\"cpu_full_frame_gate\":true,\"cpu_dispatches\":%" PRIu64 ",\"cpu_stage_values\":%" PRIu64 ",\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",validate?"false":
#ifdef YB_GPU_PROBE_HOST_ONLY
 "false",
#else
 "true",
#endif
 dispatches,(counts[0]+counts[1]+counts[2])*4,counts[0],counts[1],counts[2]);
 reported=1;
 uint64_t planned_batches=0;
 for(unsigned c=0;c<3;c++)planned_batches+=(counts[c]+GPU_BATCH-1)/GPU_BATCH;
 uint32_t planned_suffix=0;
 if(!suffix_offset((uint32_t)((counts[2]-1)%GPU_BATCH+1),last_count,&planned_suffix)){
  printf(",\"status\":\"failed\"}\n");goto end;
 }
 printf(",\"golden_suffix_offset\":%u",planned_suffix);
 printf(",\"cpu_chunk_samples\":65536,\"timed_crosscheck_scope\":\"final-CPU-subchunk-suffix-only\",\"gpu_batch_samples\":%u,\"gpu_batch_dispatches\":%" PRIu64 ",\"golden_suffix_samples\":%u",(unsigned)GPU_BATCH,planned_batches,last_count);

 reported=1;
 if(validate){printf(",\"status\":\"validated\",\"full_frame_gpu_exact\":false,\"gpu_verified_dispatches\":0,\"gpu_oracle_dispatches\":0,\"gpu_verified_stage_values\":0}\n");status=0;}
 else{
#ifdef YB_GPU_PROBE_HOST_ONLY
 (void)shader_path;printf(",\"status\":\"host-validation-build\",\"full_frame_gpu_exact\":false,\"gpu_verified_dispatches\":0,\"gpu_oracle_dispatches\":0,\"gpu_verified_stage_values\":0}\n");status=3;
#else
 int okay=gpu_run(node,shader_path,&work,&fixture,&a,&golden,last_count);
 printf(",\"status\":\"%s\"}\n",okay?"complete":"failed");status=okay?0:1;
#endif
 }
end:
 if(status && !reported)printf("{\"schema\":\"yblod.native-gpu-texture-streamed-probe.v1\",\"status\":\"failed\",\"gpu_attempted\":false,\"cpu_full_frame_gate\":false}\n");
 free(blob);free(pixels);for(int i=0;i<4;i++)free(bl[i]);
 free(el);free_stages(&a);free_stages(&b);free_stages(&golden);free(zero);return status;
}
