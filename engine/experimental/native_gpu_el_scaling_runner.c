#define _POSIX_C_SOURCE 200809L
/* Declared literal Annex-B example, tiny synthetic fixtures only. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
enum {CASES=10};
struct scale_case {unsigned component,pattern,channels,words,vertical_words;uint16_t input[32],expected_vertical[64],actual_vertical[64],expected[128],actual[128];uint32_t expected_status,actual_status;};
static struct scale_case cases[CASES];
static unsigned clamp_index(int p,unsigned extent) {return p<0?0u:(unsigned)p>=extent?extent-1u:(unsigned)p;}
static int rounded16(int n,unsigned shift)
{
    int value=n+(1<<(shift-1u));value=value>=0?value>>shift:-1-((-(value+1))>>shift);
    return value<0?0:value>65535?65535:value;
}
static int at(const struct scale_case *c,int x,int y,unsigned k)
{
    return c->input[(clamp_index(y,4)*4u+clamp_index(x,4))*c->channels+k]>>6;
}
static void prepare(void)
{
    for(unsigned i=0;i<CASES;++i) {
        struct scale_case *c=&cases[i];c->component=i/5u;c->channels=c->component?2u:1u;c->pattern=i%5u;
        c->words=64u*c->channels;c->vertical_words=32u*c->channels;
        for(unsigned y=0;y<4;++y) for(unsigned x=0;x<4;++x) for(unsigned k=0;k<c->channels;++k) {
            unsigned value=c->pattern==0?512u:c->pattern==1?64u+37u*x+83u*y+127u*k:c->pattern==2?(x==2&&y==2?128u:0u):c->pattern==3?(x>=2?1023u:0u):(x==2&&y==2?1023u:0u);
            c->input[(y*4u+x)*c->channels+k]=(uint16_t)(value<<6);
        }
        for(unsigned y=0;y<8;++y) for(unsigned x=0;x<4;++x) for(unsigned k=0;k<c->channels;++k) {
            int center=(int)(y/2u),sum=0;
            if(!c->component) {
                const int offsets[2][4]={{-2,-1,0,1},{-1,0,1,2}},weights[2][4]={{-3,29,111,-9},{-9,111,29,-3}};
                for(unsigned t=0;t<4;++t) sum+=at(c,(int)x,center+offsets[y%2u][t],k)*weights[y%2u][t];
                sum=rounded16(sum,7);
            } else {
                int first=at(c,(int)x,center+(y%2u?0:-1),k),second=at(c,(int)x,center+(y%2u?1:0),k);
                sum=rounded16(first*(y%2u?192:64)+second*(y%2u?64:192),8);
            }
            c->expected_vertical[(y*4u+x)*c->channels+k]=(uint16_t)sum;
        }
        for(unsigned y=0;y<8;++y) for(unsigned x=0;x<8;++x) {
            int result[2]={0};
            for(unsigned k=0;k<c->channels;++k) {
                if(!(x%2u)) result[k]=c->expected_vertical[(y*4u+x/2u)*c->channels+k];
                else {
                    const int weights[8]={22,94,-524,2456,2456,-524,94,22};int sum=0;
                    for(unsigned t=0;t<8;++t) sum+=c->expected_vertical[(y*4u+clamp_index((int)(x/2u)+(int)t-3,4))*c->channels+k]*weights[t];
                    result[k]=rounded16(sum,12);
                }
            }
            int rejected=result[0]>1023||result[1]>1023;
            if(rejected) c->expected_status|=4u;
            for(unsigned k=0;k<c->channels;++k) c->expected[(y*8u+x)*c->channels+k]=rejected?UINT16_MAX:(uint16_t)((unsigned)result[k]<<6);
        }
    }
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
struct gl_api {
    PFNGLGETSTRINGPROC GetString;PFNGLGETERRORPROC GetError;PFNGLGETINTEGERVPROC GetIntegerv;
    PFNGLCREATESHADERPROC CreateShader;PFNGLSHADERSOURCEPROC ShaderSource;PFNGLCOMPILESHADERPROC CompileShader;
    PFNGLGETSHADERIVPROC GetShaderiv;PFNGLDELETESHADERPROC DeleteShader;
    PFNGLGETSHADERINFOLOGPROC GetShaderInfoLog;PFNGLGETPROGRAMINFOLOGPROC GetProgramInfoLog;
    PFNGLCREATEPROGRAMPROC CreateProgram;PFNGLATTACHSHADERPROC AttachShader;PFNGLLINKPROGRAMPROC LinkProgram;
    PFNGLGETPROGRAMIVPROC GetProgramiv;PFNGLDELETEPROGRAMPROC DeleteProgram;PFNGLUSEPROGRAMPROC UseProgram;
    PFNGLGENBUFFERSPROC GenBuffers;PFNGLBINDBUFFERPROC BindBuffer;PFNGLBUFFERDATAPROC BufferData;
    PFNGLBINDBUFFERBASEPROC BindBufferBase;PFNGLDELETEBUFFERSPROC DeleteBuffers;PFNGLGETBUFFERSUBDATAPROC GetBufferSubData;
    PFNGLDISPATCHCOMPUTEPROC DispatchCompute;PFNGLMEMORYBARRIERPROC MemoryBarrier;
    PFNGLFENCESYNCPROC FenceSync;PFNGLCLIENTWAITSYNCPROC ClientWaitSync;PFNGLDELETESYNCPROC DeleteSync;
    PFNGLGETUNIFORMLOCATIONPROC GetUniformLocation;PFNGLUNIFORMMATRIX3FVPROC UniformMatrix3fv;
    PFNGLUNIFORM3FVPROC Uniform3fv;PFNGLUNIFORM1IPROC Uniform1i;PFNGLUNIFORM1UIPROC Uniform1ui;
    PFNGLGENTEXTURESPROC GenTextures;PFNGLBINDTEXTUREPROC BindTexture;PFNGLTEXIMAGE2DPROC TexImage2D;
    PFNGLGETTEXIMAGEPROC GetTexImage;PFNGLTEXPARAMETERIPROC TexParameteri;PFNGLDELETETEXTURESPROC DeleteTextures;
    PFNGLBINDIMAGETEXTUREPROC BindImageTexture;PFNGLUNIFORM2UIPROC Uniform2ui;PFNGLACTIVETEXTUREPROC ActiveTexture;
};
#define LOAD(member,type) do{gl.member=(type)eglGetProcAddress("gl" #member);if(!gl.member)goto cleanup;}while(0)
static int execute(const char *node,char *source,char renderer[1024],char version[1024])
{
    int ok=0,fd=-1,initialized=0,current=0;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[2]={0},textures[3]={0};GLsync fence=NULL;struct gl_api gl={0};struct stat requested;
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
    LOAD(GetString,PFNGLGETSTRINGPROC);LOAD(GetError,PFNGLGETERRORPROC);LOAD(GetIntegerv,PFNGLGETINTEGERVPROC);
    LOAD(CreateShader,PFNGLCREATESHADERPROC);LOAD(ShaderSource,PFNGLSHADERSOURCEPROC);LOAD(CompileShader,PFNGLCOMPILESHADERPROC);LOAD(GetShaderiv,PFNGLGETSHADERIVPROC);LOAD(DeleteShader,PFNGLDELETESHADERPROC);
    LOAD(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC);LOAD(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC);
    LOAD(CreateProgram,PFNGLCREATEPROGRAMPROC);LOAD(AttachShader,PFNGLATTACHSHADERPROC);LOAD(LinkProgram,PFNGLLINKPROGRAMPROC);LOAD(GetProgramiv,PFNGLGETPROGRAMIVPROC);LOAD(DeleteProgram,PFNGLDELETEPROGRAMPROC);LOAD(UseProgram,PFNGLUSEPROGRAMPROC);
    LOAD(GenBuffers,PFNGLGENBUFFERSPROC);LOAD(BindBuffer,PFNGLBINDBUFFERPROC);LOAD(BufferData,PFNGLBUFFERDATAPROC);LOAD(BindBufferBase,PFNGLBINDBUFFERBASEPROC);LOAD(DeleteBuffers,PFNGLDELETEBUFFERSPROC);LOAD(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC);
    LOAD(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC);LOAD(MemoryBarrier,PFNGLMEMORYBARRIERPROC);LOAD(FenceSync,PFNGLFENCESYNCPROC);LOAD(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC);LOAD(DeleteSync,PFNGLDELETESYNCPROC);
    LOAD(GetUniformLocation,PFNGLGETUNIFORMLOCATIONPROC);LOAD(UniformMatrix3fv,PFNGLUNIFORMMATRIX3FVPROC);LOAD(Uniform3fv,PFNGLUNIFORM3FVPROC);LOAD(Uniform1i,PFNGLUNIFORM1IPROC);LOAD(Uniform1ui,PFNGLUNIFORM1UIPROC);
    LOAD(GenTextures,PFNGLGENTEXTURESPROC);LOAD(BindTexture,PFNGLBINDTEXTUREPROC);LOAD(TexImage2D,PFNGLTEXIMAGE2DPROC);
    LOAD(GetTexImage,PFNGLGETTEXIMAGEPROC);LOAD(TexParameteri,PFNGLTEXPARAMETERIPROC);LOAD(DeleteTextures,PFNGLDELETETEXTURESPROC);
    LOAD(BindImageTexture,PFNGLBINDIMAGETEXTUREPROC);LOAD(Uniform2ui,PFNGLUNIFORM2UIPROC);LOAD(ActiveTexture,PFNGLACTIVETEXTUREPROC);
    const char *r=(const char *)gl.GetString(GL_RENDERER),*v=(const char *)gl.GetString(GL_VERSION);
    if(!r||!v||!strstr(r,"Intel")||strlen(r)>=1024||strlen(v)>=1024) goto cleanup;
    strcpy(renderer,r);strcpy(version,v);
    GLint max_bindings=0;gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&max_bindings);if(max_bindings<2) goto cleanup;
    shader=gl.CreateShader(GL_COMPUTE_SHADER);const GLchar *shader_text=source;gl.ShaderSource(shader,1,&shader_text,NULL);gl.CompileShader(shader);
    GLint compiled=0;gl.GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    if(!compiled) {char log[2048]={0};gl.GetShaderInfoLog(shader,(GLsizei)sizeof(log),NULL,log);fprintf(stderr,"shader compile: %s\n",log);goto cleanup;}
    program=gl.CreateProgram();gl.AttachShader(program,shader);gl.LinkProgram(program);gl.GetProgramiv(program,GL_LINK_STATUS,&compiled);
    if(!compiled) {char log[2048]={0};gl.GetProgramInfoLog(program,(GLsizei)sizeof(log),NULL,log);fprintf(stderr,"shader link: %s\n",log);goto cleanup;}
    gl.UseProgram(program);gl.GenTextures(3,textures);gl.GenBuffers(1,buffers);
    for(unsigned i=0;i<CASES;++i) {
        struct scale_case *c=&cases[i];GLenum format=c->component?GL_RG:GL_RED,integer_format=c->component?GL_RG_INTEGER:GL_RED_INTEGER;
        /* Unbind old image views before redefining shared texture formats. */
        for(unsigned unit=0;unit<4;++unit)
            gl.BindImageTexture(unit,0,0,GL_FALSE,0,GL_WRITE_ONLY,GL_R16);
        gl.ActiveTexture(GL_TEXTURE0);gl.BindTexture(GL_TEXTURE_2D,textures[0]);
        gl.TexImage2D(GL_TEXTURE_2D,0,c->component?GL_RG16:GL_R16,4,4,0,format,GL_UNSIGNED_SHORT,c->input);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl.ActiveTexture(GL_TEXTURE1);gl.BindTexture(GL_TEXTURE_2D,textures[1]);memset(c->actual_vertical,0xff,sizeof(c->actual_vertical));
        gl.TexImage2D(GL_TEXTURE_2D,0,c->component?GL_RG16UI:GL_R16UI,4,8,0,integer_format,GL_UNSIGNED_SHORT,c->actual_vertical);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl.ActiveTexture(GL_TEXTURE0);gl.BindTexture(GL_TEXTURE_2D,textures[2]);memset(c->actual,0xff,sizeof(c->actual));
        gl.TexImage2D(GL_TEXTURE_2D,0,c->component?GL_RG16:GL_R16,8,8,0,format,GL_UNSIGNED_SHORT,c->actual);
        gl.BindImageTexture(c->component?0u:1u,0,0,GL_FALSE,0,GL_WRITE_ONLY,c->component?GL_R16UI:GL_RG16UI);
        gl.BindImageTexture(c->component?2u:3u,0,0,GL_FALSE,0,GL_WRITE_ONLY,c->component?GL_R16:GL_RG16);
        gl.BindImageTexture(c->component?1u:0u,textures[1],0,GL_FALSE,0,GL_WRITE_ONLY,c->component?GL_RG16UI:GL_R16UI);
        gl.BindImageTexture(c->component?3u:2u,textures[2],0,GL_FALSE,0,GL_WRITE_ONLY,c->component?GL_RG16:GL_R16);
        gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[0]);uint32_t zero=0;gl.BufferData(GL_SHADER_STORAGE_BUFFER,(GLsizeiptr)sizeof(zero),&zero,GL_DYNAMIC_READ);gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,3,buffers[0]);
        gl.Uniform2ui(0,4,4);gl.Uniform1ui(2,c->component);gl.Uniform1ui(1,0);
        gl.BindTexture(GL_TEXTURE_2D,textures[0]);gl.DispatchCompute(1,1,1);
        gl.MemoryBarrier(GL_SHADER_IMAGE_ACCESS_BARRIER_BIT|GL_TEXTURE_FETCH_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
        gl.Uniform1ui(1,1);gl.DispatchCompute(1,1,1);gl.MemoryBarrier(GL_TEXTURE_UPDATE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
        fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);if(!fence) goto cleanup;
        GLenum status=GL_TIMEOUT_EXPIRED;for(unsigned n=0;n<5&&status==GL_TIMEOUT_EXPIRED;++n) status=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(1000000000));
        gl.DeleteSync(fence);fence=NULL;if(status!=GL_ALREADY_SIGNALED&&status!=GL_CONDITION_SATISFIED) goto cleanup;
        gl.ActiveTexture(GL_TEXTURE1);gl.BindTexture(GL_TEXTURE_2D,textures[1]);gl.GetTexImage(GL_TEXTURE_2D,0,integer_format,GL_UNSIGNED_SHORT,c->actual_vertical);
        gl.ActiveTexture(GL_TEXTURE0);gl.BindTexture(GL_TEXTURE_2D,textures[2]);gl.GetTexImage(GL_TEXTURE_2D,0,format,GL_UNSIGNED_SHORT,c->actual);
        gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(c->actual_status),&c->actual_status);
        if(gl.GetError()!=GL_NO_ERROR) goto cleanup;
    }
    ok=1;
cleanup:
    if(current) {
        if(fence&&gl.DeleteSync) gl.DeleteSync(fence);
        if(gl.DeleteTextures) gl.DeleteTextures(3,textures);
        if(gl.DeleteBuffers) gl.DeleteBuffers(2,buffers);
        if(program&&gl.DeleteProgram) gl.DeleteProgram(program);
        if(shader&&gl.DeleteShader) gl.DeleteShader(shader);
        if(gl.GetError&&gl.GetError()!=GL_NO_ERROR) ok=0;
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)) ok=0;
    }
    if(context!=EGL_NO_CONTEXT&&!eglDestroyContext(display,context)) ok=0;
    if(initialized&&!eglTerminate(display)) ok=0;
    if(fd>=0&&close(fd)) ok=0;
    return ok;
}

static void print_case(const struct scale_case *c,int actual)
{
    printf("{\"component\":%u,\"pattern\":%u,\"expected_status\":%u,\"expected_vertical\":[",c->component,c->pattern,c->expected_status);
    for(unsigned k=0;k<c->vertical_words;++k) {printf("%s%u",k?",":"",c->expected_vertical[k]);}
    printf("],\"expected_words\":[");for(unsigned k=0;k<c->words;++k) {printf("%s%u",k?",":"",c->expected[k]);}
    if(actual) {
        printf("],\"actual_status\":%u,\"actual_vertical\":[",c->actual_status);
        for(unsigned k=0;k<c->vertical_words;++k) {printf("%s%u",k?",":"",c->actual_vertical[k]);}
        printf("],\"actual_words\":[");for(unsigned k=0;k<c->words;++k) {printf("%s%u",k?",":"",c->actual[k]);}
    }
    printf("]}");
}
int main(int argc,char **argv)
{
    if(argc==2&&!strcmp(argv[1],"--cpu-oracle")) {
        prepare();printf("{\"schema\":\"yblod.el-scaling-cpu-oracle.v1\",\"gpu_executed\":false,\"cases\":[");
        for(unsigned i=0;i<CASES;++i) {if(i)putchar(',');print_case(&cases[i],0);}printf("]}\n");return 0;
    }
    if(argc!=3) {fprintf(stderr,"usage: native_gpu_el_scaling_runner DEVICE SHADER | --cpu-oracle\n");return 1;}
    if(!node_valid(argv[1])) {fprintf(stderr,"explicit render node required\n");return 1;}
    prepare();char *source=shader_read(argv[2]);if(!source) {fprintf(stderr,"bounded regular shader required\n");return 1;}
    char renderer[1024]={0},version[1024]={0};int ok=execute(argv[1],source,renderer,version);free(source);
    if(!ok) {fprintf(stderr,"bounded scaling probe failed\n");return 1;}
    printf("{\"schema\":\"yblod.gpu-el-scaling-synthetic-probe.v1\",\"complete\":true,\"cleanup_complete\":true,\"native_cpu_oracle_first\":true,\"renderer\":\"%s\",\"cases\":[",renderer);
    unsigned mismatches=0,vertical_mismatches=0,status_mismatches=0,values=0;
    for(unsigned i=0;i<CASES;++i) {
        struct scale_case *c=&cases[i];if(i)putchar(',');print_case(c,1);
        for(unsigned k=0;k<c->words;++k) if(c->actual[k]!=c->expected[k]) ++mismatches;
        for(unsigned k=0;k<c->vertical_words;++k) if(c->actual_vertical[k]!=c->expected_vertical[k]) ++vertical_mismatches;
        if(c->expected_status!=c->actual_status) ++status_mismatches;
        values+=c->words+c->vertical_words;
    }
    printf("],\"compared_words\":%u,\"final_word_mismatches\":%u,\"vertical_word_mismatches\":%u,\"status_mismatches\":%u,\"playback_tested\":false}\n",values,mismatches,vertical_mismatches,status_mismatches);
    return mismatches||vertical_mismatches||status_mismatches?1:0;
}
