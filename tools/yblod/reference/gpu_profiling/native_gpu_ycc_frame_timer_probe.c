#define _POSIX_C_SOURCE 200809L
#include "native_gpu_ycc_backend.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <fcntl.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <time.h>
int yb_gpu_diag_timer_report(unsigned stage,unsigned warmups,unsigned samples);
int yb_gpu_diag_timer_validate(unsigned stage,unsigned warmups,unsigned samples);
int yb_gpu_ycc_diag_linked_group(const yb_gpu_ycc_backend *b,uint32_t group[3]);
static uint32_t linked_workgroup[3];
static unsigned full_image_checks;
static int cleanup_succeeded=1;
static uint64_t wall_ns[32],cpu_ns[32];
static unsigned warmups=8,samples=12;
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
static void json_string(const char *s)
{
    putchar('"');for(const unsigned char *p=(const unsigned char *)(s?s:"");*p;++p) {
        if(*p=='"'||*p=='\\') printf("\\%c",*p);else if(*p<32) printf("\\u%04x",(unsigned)*p);else putchar(*p);
    }putchar('"');
}
#define GL_PROCS(X) \
 X(GetString,PFNGLGETSTRINGPROC) X(GetError,PFNGLGETERRORPROC) \
 X(GetIntegerv,PFNGLGETINTEGERVPROC) X(GetTextureSubImage,PFNGLGETTEXTURESUBIMAGEPROC) \
 X(GenTextures,PFNGLGENTEXTURESPROC) X(DeleteTextures,PFNGLDELETETEXTURESPROC) \
 X(ActiveTexture,PFNGLACTIVETEXTUREPROC) X(BindTexture,PFNGLBINDTEXTUREPROC) \
 X(TexParameteri,PFNGLTEXPARAMETERIPROC) X(TexImage2D,PFNGLTEXIMAGE2DPROC) \
 X(TexSubImage2D,PFNGLTEXSUBIMAGE2DPROC) X(GetTexImage,PFNGLGETTEXIMAGEPROC) X(PixelStorei,PFNGLPIXELSTOREIPROC)
#define DECLARE(n,t) t n;
struct gl_api {GL_PROCS(DECLARE)};
#undef DECLARE
static yb_gpu_proc loader(const char *name,void *opaque)
{(void)opaque;return (yb_gpu_proc)eglGetProcAddress(name);}
static uintptr_t owner_context(void *opaque)
{(void)opaque;return (uintptr_t)eglGetCurrentContext();}
static unsigned clamp_index(int value,unsigned limit)
{return value<0?0U:(unsigned)value>=limit?limit-1U:(unsigned)value;}
static float chroma_oracle(const uint16_t *plane,unsigned width,unsigned height,unsigned x,unsigned y)
{
 unsigned cw=width/2U,ch=height/2U;
 int first_y=y==0U?-1:(int)((2U*y-1U)/4U);
 unsigned x0=x/2U,x1=clamp_index((int)x0+1,cw);
 unsigned y0=clamp_index(first_y,ch),y1=clamp_index(first_y+1,ch);
 unsigned wx=x%2U,wy=y%2U?1U:3U;
 uint32_t numerator=(uint32_t)plane[y0*cw+x0]*(2U-wx)*(4U-wy)
  +(uint32_t)plane[y1*cw+x0]*(2U-wx)*wy
  +(uint32_t)plane[y0*cw+x1]*wx*(4U-wy)
  +(uint32_t)plane[y1*cw+x1]*wx*wy;
 return (float)numerator/32768.0f;
}
static uint64_t checked_bits;
static int number(const char *text,unsigned minimum,unsigned maximum,unsigned *value)
{
 unsigned result=0;if(!text||!*text)return 0;
 for(const char *p=text;*p;p++){
  if(*p<'0'||*p>'9'||result>maximum/10U)return 0;
  result=result*10U+(unsigned)(*p-'0');if(result>maximum)return 0;
 }
 if(result<minimum)return 0;
 *value=result;return 1;
}
static int difference(const struct timespec *a,const struct timespec *b,uint64_t *value)
{
 if(b->tv_sec<a->tv_sec)return 0;
 int64_t seconds=(int64_t)b->tv_sec-(int64_t)a->tv_sec;
 int64_t nano=(int64_t)b->tv_nsec-(int64_t)a->tv_nsec;
 if(nano<0){seconds--;nano+=INT64_C(1000000000);}
 if(seconds<0||(uint64_t)seconds>UINT64_MAX/UINT64_C(1000000000))return 0;
 *value=(uint64_t)seconds*UINT64_C(1000000000)+(uint64_t)nano;return 1;
}
static uint16_t *load_planes(const char *path,unsigned width,unsigned height)
{
 const size_t bytes=(size_t)width*height*3U;
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
 struct stat before,after;uint16_t *words=NULL;size_t used=0;
 if(fd<0)return NULL;
 if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<0||(uint64_t)before.st_size!=bytes)goto end;
 words=malloc(bytes);if(!words)goto end;
 while(used<bytes){size_t request=bytes-used;if(request>65536U)request=65536U;
  ssize_t got=read(fd,(unsigned char *)words+used,request);
  if(got<0&&errno==EINTR)continue;
  if(got<=0)goto fail;
  used+=(size_t)got;
 }
 unsigned char extra;
 if(read(fd,&extra,1)!=0||fstat(fd,&after)||before.st_ino!=after.st_ino||before.st_dev!=after.st_dev||
    before.st_size!=after.st_size||before.st_mtim.tv_sec!=after.st_mtim.tv_sec||
    before.st_mtim.tv_nsec!=after.st_mtim.tv_nsec)goto fail;
 for(size_t i=0;i<bytes/2U;i++){
  const unsigned char *raw=(const unsigned char *)words;
  uint16_t code=(uint16_t)((uint16_t)raw[2U*i]|((uint16_t)raw[2U*i+1U]<<8));
  if(code>4095U)goto fail;
  words[i]=code;
 }
 goto end;
fail:free(words);words=NULL;
end:close(fd);return words;
}
static int verify_rows(struct gl_api *gl,GLuint texture,const uint16_t *const planes[3],unsigned width,unsigned height)
{
 _Static_assert(sizeof(float)==4,"RGBA32F oracle storage");
 float actual[3840*4],expected[3840*4];
 gl->PixelStorei(GL_PACK_ALIGNMENT,4);gl->PixelStorei(GL_PACK_ROW_LENGTH,0);
 for(unsigned y=0;y<height;y++){
  gl->GetTextureSubImage(texture,0,0,(GLint)y,0,(GLsizei)width,1,1,GL_RGBA,GL_FLOAT,
      (GLsizei)((size_t)width*4U*sizeof(float)),actual);
  if(gl->GetError()!=GL_NO_ERROR)return 0;
  for(unsigned x=0;x<width;x++){
   expected[4U*x]=(float)planes[0][(size_t)y*width+x]/4096.0f;
   expected[4U*x+1U]=chroma_oracle(planes[1],width,height,x,y);
   expected[4U*x+2U]=chroma_oracle(planes[2],width,height,x,y);
   expected[4U*x+3U]=1.0f;
  }
  if(memcmp(actual,expected,(size_t)width*4U*sizeof(float)))return 0;
  checked_bits+=(uint64_t)width*4U;
 }
 return 1;
}
static int execute(const char *node,char *source,const uint16_t *raw,unsigned width,unsigned height,char renderer[1024],char version[1024])
{
 int ok=0,fd=-1,initialized=0,current=0;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
 GLuint textures[3]={0};struct gl_api gl={0};struct stat requested;yb_gpu_ycc_backend *backend=NULL;
 const char *operation="device/context setup";
 const uint16_t *planes[3]={raw,raw+(size_t)width*height,raw+(size_t)width*height*5U/4U};
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
    initialized=1;EGLAttrib device=0;
    if(!display_attribute(display,EGL_DEVICE_EXT,&device)||(EGLDeviceEXT)device!=selected) goto cleanup;
    const char *ext=eglQueryString(display,EGL_EXTENSIONS);
    if(eglGetError()!=EGL_SUCCESS||!extension(ext,"EGL_KHR_surfaceless_context")||!eglBindAPI(EGL_OPENGL_API)) goto cleanup;
    const EGLint config_attributes[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config;EGLint configs_count=0;
    if(!eglChooseConfig(display,config_attributes,&config,1,&configs_count)||configs_count!=1) goto cleanup;
    context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    if(context==EGL_NO_CONTEXT||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) goto cleanup;
    current=1;

#define LOAD(n,t) gl.n=(t)eglGetProcAddress("gl" #n);if(!gl.n)goto cleanup;
 GL_PROCS(LOAD)
#undef LOAD
 const char *r=(const char *)gl.GetString(GL_RENDERER),*v=(const char *)gl.GetString(GL_VERSION);
 if(!r||!v||strlen(r)>=1024||strlen(v)>=1024)goto cleanup;
 strcpy(renderer,r);strcpy(version,v);
 GLint major_version=0,minor_version=0;
 gl.GetIntegerv(GL_MAJOR_VERSION,&major_version);gl.GetIntegerv(GL_MINOR_VERSION,&minor_version);
 if(major_version<4||(major_version==4&&minor_version<5)||gl.GetError()!=GL_NO_ERROR)goto cleanup;
 yb_gpu_ycc_create_info info={0};info.version=1;info.get_proc=loader;info.current_context=owner_context;
 operation="backend creation";
 info.shader_source=source;info.shader_bytes=strlen(source);
 if(yb_gpu_ycc_create(&info,&backend)!=YB_GPU_BACKEND_OK)goto cleanup;
 if(!yb_gpu_ycc_diag_linked_group(backend,linked_workgroup))goto cleanup;
  operation="input texture upload";gl.GenTextures(3,textures);
  gl.PixelStorei(GL_UNPACK_ALIGNMENT,2);gl.PixelStorei(GL_UNPACK_ROW_LENGTH,0);
  for(unsigned c=0;c<3;c++){
   gl.ActiveTexture(GL_TEXTURE0+c);gl.BindTexture(GL_TEXTURE_2D,textures[c]);
   gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
   gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
   gl.TexImage2D(GL_TEXTURE_2D,0,GL_R16UI,(GLsizei)(c?width/2U:width),(GLsizei)(c?height/2U:height),0,GL_RED_INTEGER,GL_UNSIGNED_SHORT,planes[c]);
  }
  if(gl.GetError()!=GL_NO_ERROR)goto cleanup;
  yb_gpu_ycc_plan p={0};p.version=1;p.width=width;p.height=height;p.output_depth=12;p.sampling_contract=1;
  memcpy(p.textures,textures,sizeof(textures));p.frame_id[31]=1U;
  yb_gpu_ycc_output out={0};
  const unsigned timed_start=1U+warmups;
  for(unsigned pass=0;pass<timed_start+samples;pass++){
   struct timespec begin,cpu_begin,end,cpu_end;
   if(pass>=timed_start&&(clock_gettime(CLOCK_MONOTONIC,&begin)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&cpu_begin)))goto cleanup;
   operation="YCC submit";
   int submit_status=yb_gpu_ycc_submit(backend,&p);
   if(submit_status!=YB_GPU_BACKEND_OK){fprintf(stderr,"YCC diagnostic submit failed: pass=%u status=%d\n",pass,submit_status);goto cleanup;}
   if(pass==0){
    yb_gpu_ycc_backend *held=backend;
    if(yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_BUSY||yb_gpu_ycc_destroy(&backend)!=YB_GPU_BACKEND_BUSY||backend!=held)goto cleanup;
   }
   operation="YCC completion";
   int finish_status=yb_gpu_ycc_finish(backend,UINT64_C(5000000000),&out);
   if(finish_status!=YB_GPU_BACKEND_OK){fprintf(stderr,"YCC diagnostic finish failed: pass=%u status=%d\n",pass,finish_status);goto cleanup;}
   if(out.width!=width||out.height!=height||out.output_depth!=12||out.sampling_contract!=1||memcmp(out.frame_id,p.frame_id,32))goto cleanup;
   if(pass>=timed_start&&(clock_gettime(CLOCK_MONOTONIC,&end)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&cpu_end)||
      !difference(&begin,&end,&wall_ns[pass-timed_start])||!difference(&cpu_begin,&cpu_end,&cpu_ns[pass-timed_start])))goto cleanup;
   /* Both full-image oracles are outside every timed submit/finish window.
    * Only one row is read back at a time; no full RGBA32F CPU image exists. */
   if(pass==0||pass==timed_start+samples-1U){
    operation="full RGBA32F row oracle";
    if(!verify_rows(&gl,out.texture,planes,width,height))goto cleanup;
    full_image_checks++;
   }
  }
 ok=1;
cleanup:
 if(!ok)fprintf(stderr,"YCC diagnostic failed: operation=%s full_image_checks=%u float_values_compared=%" PRIu64 "\n",operation,full_image_checks,checked_bits);
 if(current){
  if(backend){int status=yb_gpu_ycc_destroy(&backend);if(status!=YB_GPU_BACKEND_OK){fprintf(stderr,"YCC cleanup backend destroy status=%d\n",status);cleanup_succeeded=0;}}
  if(gl.DeleteTextures)gl.DeleteTextures(3,textures);
  if(gl.GetError){GLenum error=gl.GetError();if(error!=GL_NO_ERROR){fprintf(stderr,"YCC cleanup GL error=%u\n",(unsigned)error);cleanup_succeeded=0;}}
  if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)){fputs("YCC cleanup clear current failed\n",stderr);cleanup_succeeded=0;}
 }
 int destroyed=0;
 if(context!=EGL_NO_CONTEXT){if(eglDestroyContext(display,context))destroyed=1;else{fputs("YCC cleanup context destroy failed\n",stderr);cleanup_succeeded=0;}}
 if(backend){if(!destroyed||yb_gpu_ycc_abandon_destroyed_context(&backend,1)!=YB_GPU_BACKEND_OK){fputs("YCC cleanup context abandonment failed\n",stderr);cleanup_succeeded=0;}}
 if(initialized&&!eglTerminate(display)){fputs("YCC cleanup EGL terminate failed\n",stderr);cleanup_succeeded=0;}
 if(!eglReleaseThread()){fputs("YCC cleanup release thread failed\n",stderr);cleanup_succeeded=0;}
 if(fd>=0&&close(fd)){fputs("YCC cleanup node close failed\n",stderr);cleanup_succeeded=0;}
 return ok&&cleanup_succeeded;
}
int main(int argc,char **argv)
{
 unsigned width=0,height=0;
 if(argc!=6||!node_valid(argv[1])||!number(argv[3],2,3840,&width)||!number(argv[4],2,2160,&height)||((width|height)&1U))return 2;
 const char *setting=getenv("YB_COMPARE_WARMUPS");
 if(setting&&!number(setting,1,32,&warmups))return 2;
 setting=getenv("YB_COMPARE_SAMPLES");
 if(setting&&!number(setting,1,32,&samples))return 2;
 char *source=shader_read(argv[2]);if(!source)return 2;
 uint16_t *planes=load_planes(argv[5],width,height);
 if(!planes){free(source);return 2;}
 char renderer[1024]={0},version[1024]={0};int ok=execute(argv[1],source,planes,width,height,renderer,version);free(source);free(planes);
 if(ok&&!yb_gpu_diag_timer_validate(2,warmups,samples))ok=0;
 printf("{\"schema\":\"yblod.gpu-ycc-frame-timer-probe.v1\",\"complete\":%s,\"cleanup_complete\":%s,\"independent_dyadic_integer_oracle\":true,\"float_values_bit_compared\":%" PRIu64 ",\"full_image_oracle_checks\":%u,\"width\":%u,\"height\":%u,\"row_readback_bytes_max\":61440,\"renderer\":",ok?"true":"false",cleanup_succeeded?"true":"false",checked_bits,full_image_checks,width,height);
 json_string(renderer);printf(",\"gl_version\":");json_string(version);
 if(ok){
  printf(",\"linked_workgroup\":[%u,%u,%u],\"workgroup_source\":\"GL_COMPUTE_WORK_GROUP_SIZE from successfully linked diagnostic shader\"",linked_workgroup[0],linked_workgroup[1],linked_workgroup[2]);
  if(!yb_gpu_diag_timer_report(2,warmups,samples))ok=0;
  printf(",\"warmups\":%u,\"samples\":%u,\"host_submit_finish_wall_ns\":[",warmups,samples);
  for(unsigned i=0;i<samples;i++)printf("%s%" PRIu64,i?",":"",wall_ns[i]);
  printf("],\"host_submit_finish_cpu_ns\":[");
  for(unsigned i=0;i<samples;i++)printf("%s%" PRIu64,i?",":"",cpu_ns[i]);
  printf("]");
 }
 puts("}");
 return ok?0:1;
}
