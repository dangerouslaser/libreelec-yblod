#define _POSIX_C_SOURCE 200809L
#include "native_colour.h"
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
enum {SAMPLES=12,CONFIGS=6};
struct gpu_colour {float stage[4][4];uint32_t status_codes[4];};
_Static_assert(sizeof(struct gpu_colour)==80,"std430 colour stride");
_Static_assert(offsetof(struct gpu_colour,status_codes)==64,"std430 status offset");
static const double samples[SAMPLES][3]={{0,0,0},{4095,4095,4095},{2048,1024,3072},
    {1,63,64},{2048.5,1024.25,4094.75},{.0001,.001,.01},{2047,2048,2049},
    {4095.0,0,2048},{-1,0,0},{4096,0,0},{NAN,0,0},{INFINITY,0,0}};
static struct yb_colour_config configs[CONFIGS];
static struct yb_colour_result cpu[CONFIGS][SAMPLES];
static int cpu_status[CONFIGS][SAMPLES];
static struct gpu_colour gpu[CONFIGS][SAMPLES];
static float inputs[SAMPLES][4];
static double input_conversion_max,uniform_conversion_max;
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
static int prepare(void)
{
    for(unsigned c=0;c<CONFIGS;++c) {
        struct yb_colour_parameters p;memset(&p,0,sizeof(p));
        for(unsigned i=0;i<9;++i) p.source_ycc[i]=p.source_lms[i]=p.target_ycc[i]=p.target_lms[i]=i%4?0:1;
        p.code_scale=4096;p.pq_policy=(c%2)?YB_PQ_EXTEND_POSITIVE_NEGATIVE_TO_ZERO:YB_PQ_REJECT_OUTSIDE_UNIT;
        if(c>=2&&c<4) {
            const double ycc[9]={8194.0/8192,799.0/8192,1681.0/8192,8194.0/8192,-933.0/8192,1091.0/8192,8194.0/8192,267.0/8192,-5545.0/8192};
            const double lms[9]={17080.0/16384,-348.0/16384,-348.0/16384,-348.0/16384,17080.0/16384,-348.0/16384,-348.0/16384,-348.0/16384,17080.0/16384};
            memcpy(p.target_ycc,ycc,sizeof(ycc));memcpy(p.target_lms,lms,sizeof(lms));
            p.target_offset[1]=p.target_offset[2]=.5;
            p.source_offset[1]=p.source_offset[2]=.5;
        }
        if(c>=4) for(unsigned i=0;i<9;++i) p.source_ycc[i]=i%4?0:2;
        if(yb_colour_init(&p,&configs[c])) return 0;
        for(unsigned s=0;s<SAMPLES;++s) cpu_status[c][s]=yb_colour_sample(&configs[c],samples[s],&cpu[c][s]);
    }
    for(unsigned s=0;s<SAMPLES;++s) for(unsigned i=0;i<3;++i) {
        inputs[s][i]=(float)samples[s][i];
        if(isfinite(samples[s][i])) input_conversion_max=fmax(input_conversion_max,fabs((double)inputs[s][i]-samples[s][i]));
    }
    return 1;
}
static void json_string(const char *s)
{
    putchar('"');for(const unsigned char *p=(const unsigned char *)(s?s:"");*p;++p) {
        if(*p=='"'||*p=='\\') printf("\\%c",*p);else if(*p<32) printf("\\u%04x",(unsigned)*p);else putchar(*p);
    }putchar('"');
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
};
#define LOAD(member,type) do{gl.member=(type)eglGetProcAddress("gl" #member);if(!gl.member)goto cleanup;}while(0)
static int uniform_array(struct gl_api *gl,GLuint program,const char *name,const double *v,unsigned count)
{
    float converted[9];for(unsigned i=0;i<count;++i) {converted[i]=(float)v[i];if(!isfinite(converted[i])) return 0;uniform_conversion_max=fmax(uniform_conversion_max,fabs((double)converted[i]-v[i]));}
    GLint location=gl->GetUniformLocation(program,name);if(location<0) return 0;
    if(count==9) gl->UniformMatrix3fv(location,1,GL_TRUE,converted);else gl->Uniform3fv(location,1,converted);
    return 1;
}
static int execute(const char *node,char *source,char renderer[1024],char version[1024])
{
    int ok=0,fd=-1,initialized=0,current=0;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[2]={0};GLsync fence=NULL;struct gl_api gl={0};struct stat requested;
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
    const char *r=(const char *)gl.GetString(GL_RENDERER),*v=(const char *)gl.GetString(GL_VERSION);
    if(!r||!v||!strstr(r,"Intel")||strlen(r)>=1024||strlen(v)>=1024) goto cleanup;
    strcpy(renderer,r);strcpy(version,v);
    GLint max_bindings=0;gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&max_bindings);if(max_bindings<2) goto cleanup;
    shader=gl.CreateShader(GL_COMPUTE_SHADER);const GLchar *shader_text=source;gl.ShaderSource(shader,1,&shader_text,NULL);gl.CompileShader(shader);
    GLint compiled=0;gl.GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    if(!compiled) {char log[2048]={0};gl.GetShaderInfoLog(shader,(GLsizei)sizeof(log),NULL,log);fprintf(stderr,"shader compile: %s\n",log);goto cleanup;}
    program=gl.CreateProgram();gl.AttachShader(program,shader);gl.LinkProgram(program);gl.GetProgramiv(program,GL_LINK_STATUS,&compiled);
    if(!compiled) {char log[2048]={0};gl.GetProgramInfoLog(program,(GLsizei)sizeof(log),NULL,log);fprintf(stderr,"shader link: %s\n",log);goto cleanup;}
    gl.UseProgram(program);gl.GenBuffers(2,buffers);
    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[0]);gl.BufferData(GL_SHADER_STORAGE_BUFFER,(GLsizeiptr)sizeof(inputs),inputs,GL_STATIC_DRAW);gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,0,buffers[0]);
    GLint count_location=gl.GetUniformLocation(program,"sample_count"),policy_location=gl.GetUniformLocation(program,"pq_policy"),scale_location=gl.GetUniformLocation(program,"code_scale");
    if(count_location<0||policy_location<0||scale_location<0) goto cleanup;
    gl.Uniform1ui(count_location,SAMPLES);gl.Uniform1i(scale_location,4096);
    for(unsigned c=0;c<CONFIGS;++c) {
        const struct yb_colour_parameters *p=&configs[c].parameters;
        if(!uniform_array(&gl,program,"source_ycc",p->source_ycc,9)||!uniform_array(&gl,program,"source_offset",p->source_offset,3)||
            !uniform_array(&gl,program,"source_lms",p->source_lms,9)||!uniform_array(&gl,program,"target_lms_inverse",configs[c].target_lms_inverse,9)||
            !uniform_array(&gl,program,"target_ycc_inverse",configs[c].target_ycc_inverse,9)||!uniform_array(&gl,program,"target_offset",p->target_offset,3)) goto cleanup;
        gl.Uniform1i(policy_location,p->pq_policy);memset(gpu[c],0xff,sizeof(gpu[c]));
        gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[1]);gl.BufferData(GL_SHADER_STORAGE_BUFFER,(GLsizeiptr)sizeof(gpu[c]),gpu[c],GL_DYNAMIC_READ);gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,1,buffers[1]);
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT);fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);if(!fence) goto cleanup;
        GLenum status=GL_TIMEOUT_EXPIRED;for(unsigned i=0;i<5&&status==GL_TIMEOUT_EXPIRED;++i) status=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(1000000000));
        gl.DeleteSync(fence);fence=NULL;if(status!=GL_ALREADY_SIGNALED&&status!=GL_CONDITION_SATISFIED) goto cleanup;
        gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(gpu[c]),gpu[c]);if(gl.GetError()!=GL_NO_ERROR) goto cleanup;
        for(unsigned s=0;s<SAMPLES;++s) {
            if(gpu[c][s].status_codes[0]>3||gpu[c][s].status_codes[0]==1) goto cleanup;
            for(unsigned k=1;k<4;++k) if(gpu[c][s].status_codes[k]>4095) goto cleanup;
            for(unsigned stage=0;stage<4;++stage) for(unsigned k=0;k<4;++k) if(!isfinite(gpu[c][s].stage[stage][k])||
                (k==3&&gpu[c][s].stage[stage][k]!=0)||
                (gpu[c][s].status_codes[0]&&gpu[c][s].stage[stage][k]!=0)) goto cleanup;
            if(gpu[c][s].status_codes[0]&&(gpu[c][s].status_codes[1]||gpu[c][s].status_codes[2]||gpu[c][s].status_codes[3])) goto cleanup;
        }
    }
    ok=1;
cleanup:
    if(current) {
        if(fence&&gl.DeleteSync) gl.DeleteSync(fence);
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
static const double *cpu_stage(const struct yb_colour_result *r,unsigned stage)
{
    return stage==0?r->source_nonlinear:stage==1?r->common_linear_lms:stage==2?r->target_linear:r->transport_before_quantization;
}
static void report(const char *renderer,const char *version)
{
    unsigned status_mismatches=0,code_diff_values=0,max_code_diff=0;double absmax[4]={0},relmax[4]={0};
    printf("{\"schema\":\"yblod.gpu-colour-synthetic-probe.v1\",\"complete\":true,\"cleanup_complete\":true,\"renderer\":");json_string(renderer);printf(",\"gl_version\":");json_string(version);
    printf(",\"native_cpu_oracle_first\":true,\"float_bit_exact_claim\":false,\"tolerance_selected\":false,\"adoption_pass\":null,\"configurations\":%d,\"samples_per_configuration\":%d,\"relative_error_floor\":1e-12,\"input_float_conversion_max_abs\":%.17g,\"uniform_float_conversion_max_abs\":%.17g,\"records\":[",CONFIGS,SAMPLES,input_conversion_max,uniform_conversion_max);
    unsigned index=0;
    for(unsigned c=0;c<CONFIGS;++c) for(unsigned s=0;s<SAMPLES;++s) {
        const struct gpu_colour *g=&gpu[c][s];unsigned status=g->status_codes[0];int cs=cpu_status[c][s];
        if(status!=(unsigned)cs) ++status_mismatches;
        printf("%s{\"configuration\":%u,\"sample\":%u,\"cpu_status\":%d,\"gpu_status\":%u",index++?",":"",c,s,cs,status);
        if(!status&&!cs) {
            printf(",\"stage_absolute_error\":[");
            for(unsigned st=0;st<4;++st) {
                const double *native=cpu_stage(&cpu[c][s],st);printf("%s[",st?",":"");
                for(unsigned k=0;k<3;++k) {double error=fabs((double)g->stage[st][k]-native[k]);absmax[st]=fmax(absmax[st],error);relmax[st]=fmax(relmax[st],error/fmax(fabs(native[k]),1e-12));printf("%s%.17g",k?",":"",error);}putchar(']');
            }
            printf("],\"cpu_codes\":[%u,%u,%u],\"gpu_codes\":[%u,%u,%u],\"code_signed_diff\":[",cpu[c][s].codes[0],cpu[c][s].codes[1],cpu[c][s].codes[2],status?0:g->status_codes[1],g->status_codes[2],g->status_codes[3]);
            for(unsigned k=0;k<3;++k) {int diff=(int)g->status_codes[k+1]-(int)cpu[c][s].codes[k];unsigned magnitude=(unsigned)(diff<0?-diff:diff);if(magnitude) ++code_diff_values;if(magnitude>max_code_diff)max_code_diff=magnitude;printf("%s%d",k?",":"",diff);}putchar(']');
        }
        putchar('}');
    }
    printf("],\"status_mismatches\":%u,\"different_code_values\":%u,\"maximum_code_difference\":%u,\"stage_max_abs\":[",status_mismatches,code_diff_values,max_code_diff);
    for(unsigned i=0;i<4;++i) {printf("%s%.17g",i?",":"",absmax[i]);}
    printf("],\"stage_max_relative\":[");
    for(unsigned i=0;i<4;++i) {printf("%s%.17g",i?",":"",relmax[i]);}
    printf("]}\n");
}
int main(int argc,char **argv)
{
    if(argc!=3) {fprintf(stderr,"usage: native_gpu_colour_runner DEVICE SHADER\n");return 1;}
    if(!node_valid(argv[1])) {fprintf(stderr,"explicit render node required\n");return 1;}
    if(!prepare()) {fprintf(stderr,"native CPU preflight failed\n");return 1;}
    char *shader=shader_read(argv[2]);if(!shader) {fprintf(stderr,"bounded regular shader required\n");return 1;}
    char renderer[1024]={0},version[1024]={0};int ok=execute(argv[1],shader,renderer,version);free(shader);
    if(!ok) {fprintf(stderr,"bounded GPU colour probe failed\n");return 1;}
    report(renderer,version);return 0;
}
