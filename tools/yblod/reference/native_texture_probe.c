#define _POSIX_C_SOURCE 200809L
#include "native_texture_fixture.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
_Static_assert(sizeof(uint32_t)==4 && sizeof(int32_t)==4 && sizeof(uint16_t)==2 && sizeof(float)==4,"wire scalar widths");

static void fixture_report(const struct yb_texture_fixture *f)
{
    printf("\"width\":8,\"height\":2,\"count\":%u,\"record_words\":36,\"parameters_u32\":[",f->parameters[0]);
    for(unsigned i=0;i<5;++i)printf("%s%u",i?",":"",f->parameters[i]);
    fputs("],\"pixels_u16\":[",stdout);
    for(unsigned i=0;i<64;++i)printf("%s%u",i?",":"",(unsigned)f->pixels[i]);
    fputs("],\"queries_i32\":[",stdout);
    for(unsigned i=0;i<YB_TEXTURE_QUERIES;++i)printf("%s[%d,%d,%d,%d]",i?",":"",f->queries[4*i],f->queries[4*i+1],f->queries[4*i+2],f->queries[4*i+3]);
    putchar(']');
}
#ifndef YB_TEXTURE_PROBE_HOST_ONLY
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
#define API(field,type) type field;
    API(GetString,PFNGLGETSTRINGPROC) API(GetIntegerv,PFNGLGETINTEGERVPROC)
    API(GetIntegeri_v,PFNGLGETINTEGERI_VPROC) API(GetInteger64v,PFNGLGETINTEGER64VPROC)
    API(GetError,PFNGLGETERRORPROC) API(GetInternalformativ,PFNGLGETINTERNALFORMATIVPROC)
    API(CreateShader,PFNGLCREATESHADERPROC) API(ShaderSource,PFNGLSHADERSOURCEPROC)
    API(CompileShader,PFNGLCOMPILESHADERPROC) API(GetShaderiv,PFNGLGETSHADERIVPROC)
    API(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC) API(DeleteShader,PFNGLDELETESHADERPROC)
    API(CreateProgram,PFNGLCREATEPROGRAMPROC) API(AttachShader,PFNGLATTACHSHADERPROC)
    API(LinkProgram,PFNGLLINKPROGRAMPROC) API(GetProgramiv,PFNGLGETPROGRAMIVPROC)
    API(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC) API(DeleteProgram,PFNGLDELETEPROGRAMPROC)
    API(UseProgram,PFNGLUSEPROGRAMPROC) API(GenBuffers,PFNGLGENBUFFERSPROC)
    API(BindBuffer,PFNGLBINDBUFFERPROC) API(BufferData,PFNGLBUFFERDATAPROC)
    API(BindBufferBase,PFNGLBINDBUFFERBASEPROC) API(DeleteBuffers,PFNGLDELETEBUFFERSPROC)
    API(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC) API(MemoryBarrier,PFNGLMEMORYBARRIERPROC)
    API(FenceSync,PFNGLFENCESYNCPROC) API(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC)
    API(DeleteSync,PFNGLDELETESYNCPROC) API(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC)
    API(GenTextures,PFNGLGENTEXTURESPROC) API(BindTexture,PFNGLBINDTEXTUREPROC)
    API(TexImage2D,PFNGLTEXIMAGE2DPROC) API(TexParameteri,PFNGLTEXPARAMETERIPROC)
    API(GetTexLevelParameteriv,PFNGLGETTEXLEVELPARAMETERIVPROC) API(DeleteTextures,PFNGLDELETETEXTURESPROC)
    API(ActiveTexture,PFNGLACTIVETEXTUREPROC) API(PixelStorei,PFNGLPIXELSTOREIPROC)
    API(GenSamplers,PFNGLGENSAMPLERSPROC) API(BindSampler,PFNGLBINDSAMPLERPROC)
    API(SamplerParameteri,PFNGLSAMPLERPARAMETERIPROC) API(DeleteSamplers,PFNGLDELETESAMPLERSPROC)
#undef API
};
#define LOAD(field,type) do {gl.field=(type)eglGetProcAddress("gl" #field);if(!gl.field)goto cleanup;}while(0)
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


static int observe(const char *node,const char *shader_path,const struct yb_texture_fixture *f)
{
    int ok=0,fd=-1,initialized=0,current=0,bound=0,cleanup_ok=1;
    const char *operation="preflight";
    EGLDisplay display=EGL_NO_DISPLAY; EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[3]={0},textures[2]={0},samplers[3]={0};
    GLsync fence=NULL; struct gl_api gl={0}; char *source=NULL;
    uint32_t actual[YB_TEXTURE_QUERIES*YB_TEXTURE_WORDS];
    for(unsigned i=0;i<YB_TEXTURE_QUERIES*YB_TEXTURE_WORDS;++i)actual[i]=UINT32_C(0x7fc00001);
    GLenum observed_gl_error=GL_NO_ERROR;
    EGLint observed_egl_error=EGL_SUCCESS;
    GLenum wait_result=0;
    struct stat requested;
    unsigned mismatches=0,nonfinite=0,endpoint_mismatches=0,invalid_flags=0,invalid_zero=0;
    const uint16_t endian=1;
    if(*(const unsigned char *)&endian!=1 || !node_valid(node))goto cleanup;
    source=read_shader(shader_path);if(!source)goto cleanup;
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
#define API(field,type) LOAD(field,type)
    API(GetString,PFNGLGETSTRINGPROC); API(GetIntegerv,PFNGLGETINTEGERVPROC);
    API(GetIntegeri_v,PFNGLGETINTEGERI_VPROC); API(GetInteger64v,PFNGLGETINTEGER64VPROC);
    API(GetError,PFNGLGETERRORPROC); API(GetInternalformativ,PFNGLGETINTERNALFORMATIVPROC);
    API(CreateShader,PFNGLCREATESHADERPROC); API(ShaderSource,PFNGLSHADERSOURCEPROC);
    API(CompileShader,PFNGLCOMPILESHADERPROC); API(GetShaderiv,PFNGLGETSHADERIVPROC);
    API(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC); API(DeleteShader,PFNGLDELETESHADERPROC);
    API(CreateProgram,PFNGLCREATEPROGRAMPROC); API(AttachShader,PFNGLATTACHSHADERPROC);
    API(LinkProgram,PFNGLLINKPROGRAMPROC); API(GetProgramiv,PFNGLGETPROGRAMIVPROC);
    API(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC); API(DeleteProgram,PFNGLDELETEPROGRAMPROC);
    API(UseProgram,PFNGLUSEPROGRAMPROC); API(GenBuffers,PFNGLGENBUFFERSPROC);
    API(BindBuffer,PFNGLBINDBUFFERPROC); API(BufferData,PFNGLBUFFERDATAPROC);
    API(BindBufferBase,PFNGLBINDBUFFERBASEPROC); API(DeleteBuffers,PFNGLDELETEBUFFERSPROC);
    API(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC); API(MemoryBarrier,PFNGLMEMORYBARRIERPROC);
    API(FenceSync,PFNGLFENCESYNCPROC); API(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC);
    API(DeleteSync,PFNGLDELETESYNCPROC); API(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC);
    API(GenTextures,PFNGLGENTEXTURESPROC); API(BindTexture,PFNGLBINDTEXTUREPROC);
    API(TexImage2D,PFNGLTEXIMAGE2DPROC); API(TexParameteri,PFNGLTEXPARAMETERIPROC);
    API(GetTexLevelParameteriv,PFNGLGETTEXLEVELPARAMETERIVPROC); API(DeleteTextures,PFNGLDELETETEXTURESPROC);
    API(ActiveTexture,PFNGLACTIVETEXTUREPROC); API(PixelStorei,PFNGLPIXELSTOREIPROC);
    API(GenSamplers,PFNGLGENSAMPLERSPROC); API(BindSampler,PFNGLBINDSAMPLERPROC);
    API(SamplerParameteri,PFNGLSAMPLERPARAMETERIPROC); API(DeleteSamplers,PFNGLDELETESAMPLERSPROC);
#undef API
    operation="desktop version and capabilities";
    const char *renderer=(const char *)gl.GetString(GL_RENDERER),*version=(const char *)gl.GetString(GL_VERSION);
    fputs(",\"renderer\":",stdout);string_json(renderer);fputs(",\"gl_version\":",stdout);string_json(version);
    GLint major=0,minor=0;gl.GetIntegerv(GL_MAJOR_VERSION,&major);gl.GetIntegerv(GL_MINOR_VERSION,&minor);
    if(software(renderer)||major<4||(major==4&&minor<3))goto cleanup;
    GLint supported=0,integer_supported=0,filter=0;
    gl.GetInternalformativ(GL_TEXTURE_2D,GL_RGBA16,GL_INTERNALFORMAT_SUPPORTED,1,&supported);
    gl.GetInternalformativ(GL_TEXTURE_2D,GL_RGBA16UI,GL_INTERNALFORMAT_SUPPORTED,1,&integer_supported);
    gl.GetInternalformativ(GL_TEXTURE_2D,GL_RGBA16,GL_FILTER,1,&filter);
    printf(",\"format_caps\":{\"rgba16_supported\":%d,\"rgba16ui_supported\":%d,\"filter\":%d}",supported,integer_supported,filter);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR || supported!=GL_TRUE || integer_supported!=GL_TRUE || filter!=GL_FULL_SUPPORT)goto cleanup;
    GLint invocations=0,size=0,groups=0,blocks=0,bindings=0,units=0,texture_size=0;
    GLint64 block_size=0;
    gl.GetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,&invocations);gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,0,&size);
    gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,0,&groups);gl.GetIntegerv(GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS,&blocks);
    gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&bindings);gl.GetInteger64v(GL_MAX_SHADER_STORAGE_BLOCK_SIZE,&block_size);
    gl.GetIntegerv(GL_MAX_COMPUTE_TEXTURE_IMAGE_UNITS,&units);gl.GetIntegerv(GL_MAX_TEXTURE_SIZE,&texture_size);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||invocations<64||size<64||groups<2||blocks<3||bindings<3||units<3||texture_size<8||block_size<(GLint64)sizeof(actual))goto cleanup;
    operation="shader compile";
    shader=gl.CreateShader(GL_COMPUTE_SHADER);if(!shader)goto cleanup;
    const GLchar *source_pointer=source;gl.ShaderSource(shader,1,&source_pointer,NULL);gl.CompileShader(shader);
    GLint compiled=0;gl.GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    char log[8192]={0};GLsizei log_length=0;gl.GetShaderInfoLog(shader,(GLsizei)sizeof(log)-1,&log_length,log);
    fputs(",\"shader_log\":",stdout);string_json(log);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||!compiled)goto cleanup;
    operation="program link";
    program=gl.CreateProgram();if(!program)goto cleanup;gl.AttachShader(program,shader);gl.LinkProgram(program);
    GLint linked=0,group[3]={0};gl.GetProgramiv(program,GL_LINK_STATUS,&linked);gl.GetProgramiv(program,GL_COMPUTE_WORK_GROUP_SIZE,group);
    memset(log,0,sizeof(log));gl.GetProgramInfoLog(program,(GLsizei)sizeof(log)-1,&log_length,log);
    fputs(",\"link_log\":",stdout);string_json(log);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||!linked||group[0]!=64||group[1]!=1||group[2]!=1)goto cleanup;
    operation="texture and sampler setup";
    gl.GenTextures(2,textures);gl.GenSamplers(3,samplers);
    if(!textures[0]||!textures[1]||!samplers[0]||!samplers[1]||!samplers[2])goto cleanup;
    gl.PixelStorei(GL_UNPACK_ALIGNMENT,2);
    for(unsigned i=0;i<2;++i){
        gl.BindTexture(GL_TEXTURE_2D,textures[i]);
        gl.TexImage2D(GL_TEXTURE_2D,0,i?GL_RGBA16UI:GL_RGBA16,8,2,0,i?GL_RGBA_INTEGER:GL_RGBA,GL_UNSIGNED_SHORT,f->pixels);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
        GLint width=0,height=0,format=0;
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
        gl.GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
        if(width!=8||height!=2||format!=(i?GL_RGBA16UI:GL_RGBA16))goto cleanup;
    }
    for(unsigned i=0;i<3;++i){
        gl.SamplerParameteri(samplers[i],GL_TEXTURE_MIN_FILTER,i==1?GL_LINEAR:GL_NEAREST);
        gl.SamplerParameteri(samplers[i],GL_TEXTURE_MAG_FILTER,i==1?GL_LINEAR:GL_NEAREST);
        gl.SamplerParameteri(samplers[i],GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        gl.SamplerParameteri(samplers[i],GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        gl.ActiveTexture(GL_TEXTURE0+i);gl.BindTexture(GL_TEXTURE_2D,textures[i==2?1:0]);gl.BindSampler(i,samplers[i]);
    }
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto cleanup;
    operation="buffers and dispatch";
    gl.GenBuffers(3,buffers);
    if(!buffers[0]||!buffers[1]||!buffers[2])goto cleanup;
    const void *data[3]={f->queries,actual,f->parameters};
    const GLsizeiptr bytes[3]={(GLsizeiptr)sizeof(f->queries),(GLsizeiptr)sizeof(actual),(GLsizeiptr)sizeof(f->parameters)};
    for(unsigned i=0;i<3;++i){gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[i]);gl.BufferData(GL_SHADER_STORAGE_BUFFER,bytes[i],data[i],GL_DYNAMIC_COPY);gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,i,buffers[i]);}
    gl.UseProgram(program);if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto cleanup;
    gl.DispatchCompute(2,1,1);gl.MemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
    fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||!fence)goto cleanup;
    operation="finite completion fence";
    wait_result=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(5000000000));
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR||(wait_result!=GL_ALREADY_SIGNALED&&wait_result!=GL_CONDITION_SATISFIED))goto cleanup;
    operation="readback and hard controls";
    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[1]);gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(actual),actual);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR)goto cleanup;
    for(unsigned i=0;i<YB_TEXTURE_QUERIES;++i){
        unsigned point=(unsigned)f->queries[4*i+3];
        for(unsigned c=0;c<4;++c){
            if(actual[36*i+c]!=f->pixels[4*point+c])++mismatches;
            uint16_t w=f->pixels[4*point+c];uint32_t value=actual[36*i+4+c];
            if((w==0&&value!=0)||(w==65535&&value!=UINT32_C(0x3f800000)))++endpoint_mismatches;
        }
        for(unsigned j=4;j<32;++j){float v;memcpy(&v,&actual[36*i+j],sizeof(v));if(!isfinite(v))++nonfinite;}
        for(unsigned c=0;c<4;++c)if(actual[36*i+32+c]>(c==3?0U:1U))++invalid_flags;
        for(unsigned j=16;j<=28;j+=4)if(actual[36*i+j+3]&UINT32_C(0x7fffffff))++invalid_zero;
        for(unsigned c=0;c<4;++c)if(!(actual[36*i+24+c]&UINT32_C(0x7fffffff))&&(actual[36*i+28+c]&UINT32_C(0x7fffffff)))++invalid_zero;
    }
    fputs(",\"records_u32\":[",stdout);
    for(unsigned i=0;i<YB_TEXTURE_QUERIES;++i){if(i)putchar(',');putchar('[');for(unsigned j=0;j<36;++j)printf("%s%u",j?",":"",actual[36*i+j]);putchar(']');}putchar(']');
    ok=!mismatches&&!nonfinite&&!endpoint_mismatches&&!invalid_flags&&!invalid_zero;
cleanup:
    if(current){
        if(fence&&gl.DeleteSync)gl.DeleteSync(fence);
        if(gl.DeleteBuffers)gl.DeleteBuffers(3,buffers);
        if(gl.DeleteSamplers)gl.DeleteSamplers(3,samplers);
        if(gl.DeleteTextures)gl.DeleteTextures(2,textures);
        if(program&&gl.DeleteProgram)gl.DeleteProgram(program);
        if(shader&&gl.DeleteShader)gl.DeleteShader(shader);
        if(gl.GetError){GLenum error=gl.GetError();if(error!=GL_NO_ERROR){if(observed_gl_error==GL_NO_ERROR)observed_gl_error=error;cleanup_ok=0;}}
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))cleanup_ok=0;
    }
    if(context!=EGL_NO_CONTEXT&&!eglDestroyContext(display,context))cleanup_ok=0;
    if(initialized&&!eglTerminate(display))cleanup_ok=0;
    if(!eglReleaseThread())cleanup_ok=0;
    EGLint last=eglGetError();if(last!=EGL_SUCCESS){if(observed_egl_error==EGL_SUCCESS)observed_egl_error=last;cleanup_ok=0;}
    if(fd>=0&&close(fd))cleanup_ok=0;
    free(source);
    printf(",\"device_binding_verified\":%s,\"cleanup_succeeded\":%s,\"observed_gl_error\":%u,\"observed_egl_error\":%d,\"fence_wait_result\":%u,\"integer_control_mismatches\":%u,\"nonfinite_values\":%u,\"endpoint_mismatches\":%u,\"invalid_guard_flags\":%u,\"invalid_zero_controls\":%u,\"status\":\"%s\",\"last_operation\":",
           bound?"true":"false",cleanup_ok?"true":"false",observed_gl_error,observed_egl_error,wait_result,mismatches,nonfinite,endpoint_mismatches,invalid_flags,invalid_zero,ok&&cleanup_ok?"observed":"failed");
    string_json(operation);
    return ok&&cleanup_ok;
}
#endif

int main(int argc,char **argv)
{
    struct yb_texture_fixture f;yb_texture_fixture_init(&f);
    if(f.parameters[0]!=YB_TEXTURE_QUERIES||f.parameters[0]>128)return 2;
    if(argc==2&&!strcmp(argv[1],"--validate")){
        fputs("{\"schema\":\"yblod.native-texture-probe.v1\",",stdout);fixture_report(&f);
        fputs(",\"gpu_attempted\":false,\"status\":\"validated\"}\n",stdout);return 0;
    }
#ifndef YB_TEXTURE_PROBE_HOST_ONLY
    if(argc==3){fputs("{\"schema\":\"yblod.native-texture-probe.v1\",",stdout);fixture_report(&f);fputs(",\"gpu_attempted\":true",stdout);int ok=observe(argv[1],argv[2],&f);fputs("}\n",stdout);return ok?0:1;}
#endif
    fputs("usage: native_texture_probe --validate | RENDER_NODE REVIEWED_SHADER\n",stderr);
    return 2;
}
