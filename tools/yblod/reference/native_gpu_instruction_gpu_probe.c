/* Tiny synthetic OFF/ON composer check. No media, playback or timing claims. */
#define _POSIX_C_SOURCE 200809L
#include "native_gpu_composer_fp32.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
static yb_gpu_proc proc(const char *name,void *opaque){(void)opaque;return (yb_gpu_proc)eglGetProcAddress(name);}
static uintptr_t owner(void *opaque){(void)opaque;return (uintptr_t)eglGetCurrentContext();}
static char *read_shader(const char *path)
{
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);struct stat st;char *s=NULL;
 if(fd<0)return NULL;
 if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<=0||st.st_size>65536)goto done;
 size_t n=(size_t)st.st_size;s=calloc(n+1,1);if(!s)goto done;
 size_t used=0;while(used<n){ssize_t r=read(fd,s+used,n-used);if(r<=0){free(s);s=NULL;goto done;}used+=(size_t)r;}
 if(memchr(s,0,n)){free(s);s=NULL;}
done:close(fd);return s;
}
static EGLDisplay display=EGL_NO_DISPLAY;
static EGLContext context=EGL_NO_CONTEXT;
static int init(const char *node)
{
 struct stat requested;if(stat(node,&requested)||!S_ISCHR(requested.st_mode))return 0;
 PFNEGLQUERYDEVICESEXTPROC enumerate=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
 PFNEGLQUERYDEVICESTRINGEXTPROC name=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
 PFNEGLGETPLATFORMDISPLAYEXTPROC platform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
 if(!enumerate||!name||!platform)return 0;
 EGLDeviceEXT devices[32],selected=EGL_NO_DEVICE_EXT;EGLint count=0;unsigned matches=0;
 if(!enumerate(32,devices,&count)||count<1||count>32)return 0;
 for(EGLint i=0;i<count;i++){const char *path=name(devices[i],EGL_DRM_RENDER_NODE_FILE_EXT);struct stat st;
  if(path&&!stat(path,&st)&&S_ISCHR(st.st_mode)&&st.st_rdev==requested.st_rdev){selected=devices[i];matches++;}}
 if(matches!=1)return 0;
 display=platform(EGL_PLATFORM_DEVICE_EXT,selected,NULL);EGLint major=0,minor=0;
 if(display==EGL_NO_DISPLAY||!eglInitialize(display,&major,&minor)||!eglBindAPI(EGL_OPENGL_API))return 0;
 EGLConfig config;EGLint found=0;
 const EGLint ca[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
 const EGLint attr[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
 if(!eglChooseConfig(display,ca,&config,1,&found)||found!=1)return 0;
 context=eglCreateContext(display,config,EGL_NO_CONTEXT,attr);
 return context!=EGL_NO_CONTEXT&&eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context);
}
#define FUNCS(X) X(GetString,PFNGLGETSTRINGPROC) X(GetError,PFNGLGETERRORPROC) X(GenTextures,PFNGLGENTEXTURESPROC) X(DeleteTextures,PFNGLDELETETEXTURESPROC) X(ActiveTexture,PFNGLACTIVETEXTUREPROC) X(BindTexture,PFNGLBINDTEXTUREPROC) X(TexParameteri,PFNGLTEXPARAMETERIPROC) X(TexImage2D,PFNGLTEXIMAGE2DPROC) X(GetTexImage,PFNGLGETTEXIMAGEPROC) X(PixelStorei,PFNGLPIXELSTOREIPROC)
#define DECL(n,t) static t n;
FUNCS(DECL)
#undef DECL
int main(int argc,char **argv)
{
 int result=1;const char *stage="arguments/shader/context";char *shader=NULL;GLuint textures[5]={0};yb_gpu_fp32 *engines[2]={0};
 uint16_t data[512],baseline[3][256],actual[256];uint64_t values=0;
 if(argc!=3||strcmp(argv[1],"/dev/dri/renderD128")||(shader=read_shader(argv[2]))==NULL||!init(argv[1]))goto cleanup;
#define LOAD(n,t) n=(t)eglGetProcAddress("gl" #n);if(!n)goto cleanup;
 FUNCS(LOAD)
#undef LOAD
 stage="create";yb_gpu_backend_create_info info={0};info.version=1;info.get_proc=proc;info.current_context=owner;info.shader_source=shader;info.shader_bytes=strlen(shader);
 for(unsigned e=0;e<2;e++){yb_gpu_fp32_options o={0};o.version=1;o.flags=YB_GPU_FP32_NLQ_LUT|(e?YB_GPU_FP32_IMMUTABLE_INSTRUCTIONS:0);
  if(yb_gpu_fp32_create_ex(&info,&o,&engines[e])!=YB_GPU_BACKEND_OK)goto cleanup;}
 for(unsigned f=0;f<3;f++){
  stage="texture allocation";
  unsigned width=f==0?4U:f==1?8U:16U,height=f==0?4U:f==1?6U:12U;
  DeleteTextures(5,textures);memset(textures,0,sizeof(textures));GenTextures(5,textures);
  PixelStorei(GL_UNPACK_ALIGNMENT,2);PixelStorei(GL_UNPACK_ROW_LENGTH,0);
  for(unsigned t=0;t<5;t++){
   unsigned w=t==1||t==2||t==4?width/2:width,h=t==1||t==2||t==4?height/2:height,channels=t==1||t==4?2U:1U;
   for(unsigned i=0;i<w*h*channels;i++)data[i]=(uint16_t)(t==2?(i*73U+f*13U)%1024U:((i*97U+t*101U+f*17U)%1024U)*64U);
   ActiveTexture(GL_TEXTURE0+t);BindTexture(GL_TEXTURE_2D,textures[t]);
   TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
   TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
   TexImage2D(GL_TEXTURE_2D,0,channels==2?GL_RG16:GL_R16,(GLsizei)w,(GLsizei)h,0,channels==2?GL_RG:GL_RED,GL_UNSIGNED_SHORT,data);
  }
  if(GetError()!=GL_NO_ERROR)goto cleanup;
  yb_gpu_backend_plan p={0};p.version=1;p.width=width;p.height=height;p.input_format=1;p.enhancement_enabled=1;p.output_depth=12;
  p.mapping.bit_depth=10;p.mapping.denominator=16;memcpy(p.textures,textures,sizeof(textures));
  p.frame_id[0]=p.guide_frame_id[0]=p.enhancement_frame_id[0]=(uint8_t)(f+1U);p.guide_contract_id[0]=2;p.enhancement_scale_contract_id[0]=3;
  for(unsigned c=0;c<3;c++){struct yb_component_mapping *curve=&p.mapping.components[c];curve->pivot_count=2;curve->pivots[1]=1023;
   curve->segments[0].method=YB_POLYNOMIAL;curve->segments[0].order=1;curve->segments[0].coefficients[0][1]=65536-(int64_t)(f*c);
   p.nlq[c].bit_depth=10;p.nlq[c].denominator=16;p.nlq[c].offset=512;}
  stage="submit/finish/readback";for(unsigned e=0;e<2;e++){
   yb_gpu_backend_output out={0};int rc=yb_gpu_fp32_submit(engines[e],&p);
   if(rc!=YB_GPU_BACKEND_OK){fprintf(stderr,"submit %u/%u status %d\n",f,e,rc);goto cleanup;}
   rc=yb_gpu_fp32_finish(engines[e],UINT64_C(5000000000),&out);
   if(yb_gpu_fp32_selected(engines[e])!=1||rc!=YB_GPU_BACKEND_OK){fprintf(stderr,"finish %u/%u status%d selected%d\n",f,e,rc,yb_gpu_fp32_selected(engines[e]));goto cleanup;}
   if(out.width!=width||out.height!=height||out.output_depth!=12||memcmp(out.frame_id,p.frame_id,32))goto cleanup;
   for(unsigned c=0;c<3;c++){size_t n=(size_t)width*height/(c?4U:1U);ActiveTexture(GL_TEXTURE0);BindTexture(GL_TEXTURE_2D,out.textures[c]);
    PixelStorei(GL_PACK_ALIGNMENT,2);PixelStorei(GL_PACK_ROW_LENGTH,0);GetTexImage(GL_TEXTURE_2D,0,GL_RED_INTEGER,GL_UNSIGNED_SHORT,actual);
    GLenum glerr=GetError();if(glerr!=GL_NO_ERROR){fprintf(stderr,"readback %u/%u/%u GL0x%x\n",f,e,c,glerr);goto cleanup;}
    if(!e)memcpy(baseline[c],actual,n*sizeof(uint16_t));else{if(memcmp(baseline[c],actual,n*sizeof(uint16_t))){fprintf(stderr,"difference %u/%u\n",f,c);goto cleanup;}values+=n;}}
  }
 }
 stage="stats";for(unsigned e=0;e<2;e++){yb_gpu_fp32_instruction_stats s={0};s.version=1;
  if(yb_gpu_fp32_get_instruction_stats(engines[e],&s,sizeof(s))||s.enabled!=e||s.accepted_frames!=3||s.metadata_uploads!=(e?3U:9U)||s.range_bindings!=(e?9U:0U)||s.dispatches!=9)goto cleanup;}
 fprintf(stdout,"{\"schema\":\"yblod.immutable-instructions-gpu-probe.v1\",\"complete\":true,\"fixtures\":3,\"exact_integer_values\":%llu,\"legacy_uploads\":9,\"immutable_uploads\":3,\"immutable_range_bindings\":9,\"fp32_dispatches_each\":9,\"gpu_execution\":true}\n",(unsigned long long)values);
 fprintf(stderr,"GL renderer: %s\nGL version: %s\n",GetString(GL_RENDERER),GetString(GL_VERSION));result=0;
cleanup:
 if(result)fprintf(stderr,"probe failed at %s EGL error0x%x\n",stage,(unsigned)eglGetError());
 for(unsigned e=0;e<2;e++)if(engines[e]&&yb_gpu_fp32_destroy(&engines[e])!=YB_GPU_BACKEND_OK)result=1;
 if(DeleteTextures)DeleteTextures(5,textures);
 if(display!=EGL_NO_DISPLAY){eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);if(context!=EGL_NO_CONTEXT)eglDestroyContext(display,context);eglTerminate(display);}
 free(shader);return result;
}
