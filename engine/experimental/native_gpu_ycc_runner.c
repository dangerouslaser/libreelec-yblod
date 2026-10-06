#define _POSIX_C_SOURCE 200809L
#include "native_gpu_ycc_backend.h"
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
static int prepare_fixture(unsigned width,unsigned height,uint16_t planes[3][64],float expected[256])
{
 if(!width||!height||width*height>64U)return 0;
 unsigned count=width*height;
 for(unsigned c=0;c<3;c++)for(unsigned i=0;i<(c?count/4U:count);i++)
  planes[c][i]=(uint16_t)((i*997U+c*333U)%4096U);
 for(unsigned c=0;c<3;c++){planes[c][0]=0;planes[c][(c?count/4U:count)-1U]=4095;}
 for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++){
  unsigned i=y*width+x;
  expected[4U*i]=(float)planes[0][i]/4096.0f;
  expected[4U*i+1U]=chroma_oracle(planes[1],width,height,x,y);
  expected[4U*i+2U]=chroma_oracle(planes[2],width,height,x,y);
  expected[4U*i+3U]=1.0f;
 }
 return 1;
}
static int execute(const char *node,char *source,char renderer[1024],char version[1024])
{
 int ok=0,fd=-1,initialized=0,current=0;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
 GLuint textures[3]={0};struct gl_api gl={0};struct stat requested;yb_gpu_ycc_backend *backend=NULL;
 uint16_t planes[3][64];float expected[256],actual[256];
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
 yb_gpu_ycc_create_info info={0};info.version=1;info.get_proc=loader;info.current_context=owner_context;
 info.shader_source=source;info.shader_bytes=strlen(source);
 if(yb_gpu_ycc_create(&info,&backend)!=YB_GPU_BACKEND_OK)goto cleanup;
 for(unsigned fixture=0;fixture<2;fixture++){
  unsigned width=fixture?8U:4U,height=fixture?6U:4U;
  if(!prepare_fixture(width,height,planes,expected))goto cleanup;
  gl.DeleteTextures(3,textures);memset(textures,0,sizeof(textures));gl.GenTextures(3,textures);
  gl.PixelStorei(GL_UNPACK_ALIGNMENT,2);gl.PixelStorei(GL_UNPACK_ROW_LENGTH,0);
  for(unsigned c=0;c<3;c++){
   gl.ActiveTexture(GL_TEXTURE0+c);gl.BindTexture(GL_TEXTURE_2D,textures[c]);
   gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
   gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
   gl.TexImage2D(GL_TEXTURE_2D,0,GL_R16UI,(GLsizei)(c?width/2U:width),(GLsizei)(c?height/2U:height),0,GL_RED_INTEGER,GL_UNSIGNED_SHORT,planes[c]);
  }
  if(gl.GetError()!=GL_NO_ERROR)goto cleanup;
  yb_gpu_ycc_plan p={0};p.version=1;p.width=width;p.height=height;p.output_depth=12;p.sampling_contract=1;
  memcpy(p.textures,textures,sizeof(textures));p.frame_id[31]=(uint8_t)(fixture+1U);
  yb_gpu_ycc_output out={0};
  if(yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_OK)goto cleanup;
  yb_gpu_ycc_backend *held=backend;
  if(yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_BUSY||yb_gpu_ycc_destroy(&backend)!=YB_GPU_BACKEND_BUSY||backend!=held)goto cleanup;
  if(yb_gpu_ycc_finish(backend,UINT64_C(5000000000),&out)!=YB_GPU_BACKEND_OK)goto cleanup;
  if(out.width!=width||out.height!=height||out.output_depth!=12||out.sampling_contract!=1||memcmp(out.frame_id,p.frame_id,32))goto cleanup;
  gl.ActiveTexture(GL_TEXTURE3);gl.BindTexture(GL_TEXTURE_2D,out.texture);
  gl.PixelStorei(GL_PACK_ALIGNMENT,4);gl.PixelStorei(GL_PACK_ROW_LENGTH,0);
  gl.GetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_FLOAT,actual);
  if(gl.GetError()!=GL_NO_ERROR||memcmp(actual,expected,(size_t)width*height*4U*sizeof(float)))goto cleanup;
  checked_bits+=(uint64_t)width*height*4U;
  /* Integer texture completeness is required even for texelFetch. */
  gl.ActiveTexture(GL_TEXTURE0);gl.BindTexture(GL_TEXTURE_2D,textures[0]);
  gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
  if(yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_UNSUPPORTED)goto cleanup;
  gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
  gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
  if(yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_UNSUPPORTED)goto cleanup;
  gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
  /* Invalid code must reject the whole frame and preserve output descriptor. */
  uint16_t invalid=4096;
  gl.ActiveTexture(GL_TEXTURE1);gl.BindTexture(GL_TEXTURE_2D,textures[1]);
  gl.TexSubImage2D(GL_TEXTURE_2D,0,0,0,1,1,GL_RED_INTEGER,GL_UNSIGNED_SHORT,&invalid);
  if(gl.GetError()!=GL_NO_ERROR||yb_gpu_ycc_submit(backend,&p)!=YB_GPU_BACKEND_OK)goto cleanup;
  yb_gpu_ycc_output sentinel;memset(&sentinel,0x5a,sizeof(sentinel));out=sentinel;
  if(yb_gpu_ycc_finish(backend,UINT64_C(5000000000),&out)!=YB_GPU_BACKEND_FRAME_REJECTED||memcmp(&out,&sentinel,sizeof(out)))goto cleanup;
 }
 ok=1;
cleanup:
 if(current){
  if(backend&&yb_gpu_ycc_destroy(&backend)!=YB_GPU_BACKEND_OK)ok=0;
  if(gl.DeleteTextures)gl.DeleteTextures(3,textures);
  if(gl.GetError&&gl.GetError()!=GL_NO_ERROR)ok=0;
  if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))ok=0;
 }
 int destroyed=0;
 if(context!=EGL_NO_CONTEXT){if(eglDestroyContext(display,context))destroyed=1;else ok=0;}
 if(backend){if(!destroyed||yb_gpu_ycc_abandon_destroyed_context(&backend,1)!=YB_GPU_BACKEND_OK)ok=0;}
 if(initialized&&!eglTerminate(display))ok=0;
 if(!eglReleaseThread())ok=0;
 if(fd>=0&&close(fd))ok=0;
 return ok;
}
int main(int argc,char **argv)
{
 if(argc!=3||!node_valid(argv[1]))return 2;
 char *source=shader_read(argv[2]);if(!source)return 2;
 /* Independent dyadic integer-weighted oracle is prepared before GPU. */
 uint16_t planes[3][64];float expected[256];
 if(!prepare_fixture(4,4,planes,expected)||!prepare_fixture(8,6,planes,expected)){free(source);return 1;}
 char renderer[1024]={0},version[1024]={0};int ok=execute(argv[1],source,renderer,version);free(source);
 printf("{\"schema\":\"yblod.gpu-ycc-image-synthetic-probe.v1\",\"complete\":%s,\"cleanup_complete\":%s,\"native_cpu_oracle_first\":true,\"float_bits_checked\":%llu,\"fixtures\":2,\"invalid_code_frame_rejections\":%u,\"invalid_integer_filter_rejections\":%u,\"renderer\":",ok?"true":"false",ok?"true":"false",(unsigned long long)checked_bits,ok?2U:0U,ok?4U:0U);
 json_string(renderer);printf(",\"gl_version\":");json_string(version);puts("}");
 return ok?0:1;
}
