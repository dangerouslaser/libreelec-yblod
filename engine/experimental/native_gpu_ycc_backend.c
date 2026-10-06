#include "native_gpu_ycc_backend.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
static int nonzero(const uint8_t token[32])
{unsigned value=0;for(unsigned i=0;i<32;i++)value|=token[i];return value!=0;}
int yb_gpu_ycc_validate_plan(const yb_gpu_ycc_plan *p)
{
 if(!p||(uintptr_t)p%_Alignof(yb_gpu_ycc_plan)||p->version!=1||!p->width||!p->height||p->width>3840||p->height>2160||((p->width|p->height)&1U)||!nonzero(p->frame_id))return YB_GPU_BACKEND_ARGUMENT;
 for(unsigned i=0;i<3;i++){if(!p->textures[i])return YB_GPU_BACKEND_ARGUMENT;for(unsigned j=0;j<i;j++)if(p->textures[i]==p->textures[j])return YB_GPU_BACKEND_ARGUMENT;}
 if(p->output_depth!=12||p->sampling_contract!=1)return YB_GPU_BACKEND_UNSUPPORTED;
 return YB_GPU_BACKEND_OK;
}
#ifndef YB_GPU_YCC_HOST_ONLY
#include <GL/glcorearb.h>
#define GL_PROCS(X) \
 X(GetString,PFNGLGETSTRINGPROC) X(GetStringi,PFNGLGETSTRINGIPROC) \
 X(GetIntegerv,PFNGLGETINTEGERVPROC) X(GetIntegeri_v,PFNGLGETINTEGERI_VPROC) X(GetError,PFNGLGETERRORPROC) \
 X(CreateShader,PFNGLCREATESHADERPROC) X(ShaderSource,PFNGLSHADERSOURCEPROC) X(CompileShader,PFNGLCOMPILESHADERPROC) \
 X(GetShaderiv,PFNGLGETSHADERIVPROC) X(DeleteShader,PFNGLDELETESHADERPROC) \
 X(CreateProgram,PFNGLCREATEPROGRAMPROC) X(AttachShader,PFNGLATTACHSHADERPROC) X(LinkProgram,PFNGLLINKPROGRAMPROC) \
 X(GetProgramiv,PFNGLGETPROGRAMIVPROC) X(DeleteProgram,PFNGLDELETEPROGRAMPROC) X(UseProgram,PFNGLUSEPROGRAMPROC) \
 X(GenBuffers,PFNGLGENBUFFERSPROC) X(BindBuffer,PFNGLBINDBUFFERPROC) X(BufferData,PFNGLBUFFERDATAPROC) \
 X(BufferSubData,PFNGLBUFFERSUBDATAPROC) X(BindBufferBase,PFNGLBINDBUFFERBASEPROC) X(DeleteBuffers,PFNGLDELETEBUFFERSPROC) \
 X(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC) X(GenTextures,PFNGLGENTEXTURESPROC) X(ActiveTexture,PFNGLACTIVETEXTUREPROC) \
 X(BindTexture,PFNGLBINDTEXTUREPROC) X(TexParameteri,PFNGLTEXPARAMETERIPROC) X(TexStorage2D,PFNGLTEXSTORAGE2DPROC) \
 X(GetTexLevelParameteriv,PFNGLGETTEXLEVELPARAMETERIVPROC) X(GetTexParameteriv,PFNGLGETTEXPARAMETERIVPROC) \
 X(IsTexture,PFNGLISTEXTUREPROC) X(DeleteTextures,PFNGLDELETETEXTURESPROC) X(BindSampler,PFNGLBINDSAMPLERPROC) \
 X(BindImageTexture,PFNGLBINDIMAGETEXTUREPROC) X(Uniform2i,PFNGLUNIFORM2IPROC) X(Uniform1ui,PFNGLUNIFORM1UIPROC) \
 X(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC) X(MemoryBarrier,PFNGLMEMORYBARRIERPROC) \
 X(FenceSync,PFNGLFENCESYNCPROC) X(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC) X(DeleteSync,PFNGLDELETESYNCPROC)
#define DECLARE(field,type) type field;
struct backend_gl { GL_PROCS(DECLARE) };
#undef DECLARE
struct yb_gpu_ycc_backend {
    struct backend_gl gl;
    yb_gpu_ycc_create_info owner;
    uintptr_t context;
    GLuint program,buffers[1],outputs[1];
    GLsync fence;
    uint32_t width,height,output_depth;
    uint8_t frame_id[32];
    int pending,valid,failed,closing;
};
static int same_context(const yb_gpu_ycc_backend *b)
{return b&&b->owner.current_context&&b->owner.current_context(b->owner.opaque)==b->context;}
static int software_renderer(const char *name)
{
    if(!name)return 1;
    char lower[4096];size_t n=strlen(name);if(n>=sizeof(lower))return 1;
    for(size_t i=0;i<=n;i++)lower[i]=(char)tolower((unsigned char)name[i]);
    return strstr(lower,"llvmpipe")||strstr(lower,"softpipe")||strstr(lower,"software")||strstr(lower,"swrast");
}
static void delete_owned(yb_gpu_ycc_backend *b)
{
    b->gl.DeleteTextures(1,b->outputs);b->gl.DeleteBuffers(1,b->buffers);
    if(b->program)b->gl.DeleteProgram(b->program);
}

int yb_gpu_ycc_create(const yb_gpu_ycc_create_info *info,yb_gpu_ycc_backend **output)
{
    if(!info||!output||*output||!info->get_proc||!info->current_context||info->version!=1||
       !info->shader_source||!info->shader_bytes||info->shader_bytes>65536||
       memchr(info->shader_source,0,info->shader_bytes))return YB_GPU_BACKEND_ARGUMENT;
    uintptr_t context=info->current_context(info->opaque);if(!context)return YB_GPU_BACKEND_ARGUMENT;
    const uint16_t endian=1;if(*(const uint8_t *)&endian!=1)return YB_GPU_BACKEND_UNSUPPORTED;
    yb_gpu_ycc_backend *b=calloc(1,sizeof(*b));if(!b)return YB_GPU_BACKEND_GL_FAILURE;
    b->owner=*info;b->context=context;
#define LOAD(field,type) b->gl.field=(type)info->get_proc("gl" #field,info->opaque);if(!b->gl.field){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
    GL_PROCS(LOAD)
#undef LOAD
    struct backend_gl *g=&b->gl;
    GLint major=0,minor=0,extensions=0;
    if(g->GetError()!=GL_NO_ERROR){free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    g->GetIntegerv(GL_MAJOR_VERSION,&major);g->GetIntegerv(GL_MINOR_VERSION,&minor);g->GetIntegerv(GL_NUM_EXTENSIONS,&extensions);
    if(major<4||(major==4&&minor<3)||extensions<0||extensions>8192||
       software_renderer((const char *)g->GetString(GL_RENDERER))){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
    GLint units=0,images=0,invocations=0,sx=0,sy=0;
    g->GetIntegerv(GL_MAX_COMPUTE_TEXTURE_IMAGE_UNITS,&units);g->GetIntegerv(GL_MAX_COMPUTE_IMAGE_UNIFORMS,&images);
    g->GetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,&invocations);
    g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,0,&sx);g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,1,&sy);
    if(units<3||images<1||invocations<64||sx<8||sy<8||g->GetError()!=GL_NO_ERROR){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
    GLuint shader=g->CreateShader(GL_COMPUTE_SHADER);
    if(!shader){free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    GLint length=(GLint)info->shader_bytes;
    g->ShaderSource(shader,1,&info->shader_source,&length);g->CompileShader(shader);
    GLint compiled=0;g->GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    b->program=g->CreateProgram();
    if(compiled&&b->program){g->AttachShader(b->program,shader);g->LinkProgram(b->program);}
    g->DeleteShader(shader);
    GLint linked=0,group[3]={0,0,0};
    if(b->program){g->GetProgramiv(b->program,GL_LINK_STATUS,&linked);if(linked)g->GetProgramiv(b->program,GL_COMPUTE_WORK_GROUP_SIZE,group);}
    if(!compiled||!linked||group[0]!=8||group[1]!=8||group[2]!=1||g->GetError()!=GL_NO_ERROR){
        if(b->program)g->DeleteProgram(b->program);
        free(b);return YB_GPU_BACKEND_GL_FAILURE;
    }
    g->GenBuffers(1,b->buffers);
    for(unsigned i=0;i<1;i++){
        if(!b->buffers[i]){delete_owned(b);free(b);return YB_GPU_BACKEND_GL_FAILURE;}
        g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[i]);
        g->BufferData(GL_SHADER_STORAGE_BUFFER,4,NULL,GL_DYNAMIC_COPY);
    }
    if(g->GetError()!=GL_NO_ERROR){delete_owned(b);free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    *output=b;return YB_GPU_BACKEND_OK;
}

static int validate_texture(yb_gpu_ycc_backend *b,const yb_gpu_ycc_plan *p,unsigned slot)
{
    struct backend_gl *g=&b->gl;
    int half=slot!=0;
    if(!g->IsTexture(p->textures[slot]))return 0;
    for(unsigned i=0;i<1;i++)if(p->textures[slot]==b->outputs[i])return 0;
    g->ActiveTexture(GL_TEXTURE0+slot);g->BindTexture(GL_TEXTURE_2D,p->textures[slot]);g->BindSampler(slot,0);
    GLint width=0,height=0,format=0,base=0,max=0,min_filter=0,mag_filter=0,swizzle[4]={0,0,0,0};
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,&base);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,&max);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,&min_filter);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,&mag_filter);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_SWIZZLE_RGBA,swizzle);
    return width==(GLint)(half?p->width/2U:p->width)&&height==(GLint)(half?p->height/2U:p->height)&&
       format==GL_R16UI&&base==0&&max>=0&&
       min_filter==GL_NEAREST&&mag_filter==GL_NEAREST&&
       swizzle[0]==GL_RED&&swizzle[1]==GL_GREEN&&swizzle[2]==GL_BLUE&&swizzle[3]==GL_ALPHA&&g->GetError()==GL_NO_ERROR;
}

int yb_gpu_ycc_submit(yb_gpu_ycc_backend *b,const yb_gpu_ycc_plan *p)
{
    int status=yb_gpu_ycc_validate_plan(p);if(status)return status;
    if(!same_context(b))return YB_GPU_BACKEND_ARGUMENT;
    if(b->pending||b->closing)return YB_GPU_BACKEND_BUSY;
    struct backend_gl *g=&b->gl;
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    GLint limit=0,gx=0,gy=0;
    g->GetIntegerv(GL_MAX_TEXTURE_SIZE,&limit);
    g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,0,&gx);g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,1,&gy);
    if(limit<(GLint)p->width||limit<(GLint)p->height||gx<(GLint)((p->width+7U)/8U)||gy<(GLint)((p->height+7U)/8U))return YB_GPU_BACKEND_UNSUPPORTED;
    for(unsigned slot=0;slot<3;slot++)if(!validate_texture(b,p,slot))return YB_GPU_BACKEND_UNSUPPORTED;
    int resize=b->width!=p->width||b->height!=p->height;
    GLuint fresh[1]={0};
    if(resize){
        g->GenTextures(1,fresh);
        for(unsigned c=0;c<1;c++){
            if(!fresh[c]){g->DeleteTextures(1,fresh);return YB_GPU_BACKEND_GL_FAILURE;}
            g->ActiveTexture(GL_TEXTURE5);g->BindTexture(GL_TEXTURE_2D,fresh[c]);
            g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
            g->TexStorage2D(GL_TEXTURE_2D,1,GL_RGBA32F,(GLsizei)p->width,(GLsizei)p->height);
        }
        if(g->GetError()!=GL_NO_ERROR){g->DeleteTextures(1,fresh);return YB_GPU_BACKEND_GL_FAILURE;}
    }
    b->valid=0;b->failed=0;
    const uint32_t zero=0;
    g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[0]);g->BufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&zero);
    g->BindBufferBase(GL_SHADER_STORAGE_BUFFER,0,b->buffers[0]);
    g->UseProgram(b->program);g->Uniform2i(0,(GLint)p->width,(GLint)p->height);
    g->Uniform1ui(1,p->sampling_contract);g->Uniform1ui(2,p->output_depth);
    g->BindImageTexture(0,resize?fresh[0]:b->outputs[0],0,GL_FALSE,0,GL_WRITE_ONLY,GL_RGBA32F);
    g->DispatchCompute((p->width+7U)/8U,(p->height+7U)/8U,1);
    g->MemoryBarrier(GL_SHADER_IMAGE_ACCESS_BARRIER_BIT|GL_TEXTURE_FETCH_BARRIER_BIT|GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
    b->fence=g->FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    /* Even if a GL error occurs after queueing, retain pending work so caller
     * cannot recycle borrowed inputs before completion. */
    if(resize){g->DeleteTextures(1,b->outputs);memcpy(b->outputs,fresh,sizeof(fresh));}
    b->width=p->width;b->height=p->height;b->output_depth=(uint32_t)p->output_depth;memcpy(b->frame_id,p->frame_id,32);
    b->pending=1;
    if(!b->fence||g->GetError()!=GL_NO_ERROR){b->failed=1;return YB_GPU_BACKEND_GL_FAILURE;}
    return YB_GPU_BACKEND_OK;
}

int yb_gpu_ycc_finish(yb_gpu_ycc_backend *b,uint64_t timeout,yb_gpu_ycc_output *output)
{
    if(!output||(uintptr_t)output%_Alignof(yb_gpu_ycc_output)||timeout>UINT64_C(5000000000)||!same_context(b))return YB_GPU_BACKEND_ARGUMENT;
    if(!b->pending)return YB_GPU_BACKEND_ARGUMENT;
    if(!b->fence)return YB_GPU_BACKEND_GL_FAILURE;
    struct backend_gl *g=&b->gl;
    GLenum waited=g->ClientWaitSync(b->fence,GL_SYNC_FLUSH_COMMANDS_BIT,timeout);
    if(waited==GL_TIMEOUT_EXPIRED)return YB_GPU_BACKEND_PENDING;
    if((waited!=GL_ALREADY_SIGNALED&&waited!=GL_CONDITION_SATISFIED)||g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    g->DeleteSync(b->fence);b->fence=NULL;b->pending=0;
    if(b->failed)return YB_GPU_BACKEND_GL_FAILURE;
    uint32_t error=UINT32_MAX;
    g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[0]);g->GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&error);
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    if(error)return YB_GPU_BACKEND_FRAME_REJECTED;
    yb_gpu_ycc_output value={0};value.version=1;value.width=b->width;value.height=b->height;value.output_depth=b->output_depth;
    value.texture=b->outputs[0];value.sampling_contract=1;memcpy(value.frame_id,b->frame_id,32);
    b->valid=1;*output=value;return YB_GPU_BACKEND_OK;
}

int yb_gpu_ycc_destroy(yb_gpu_ycc_backend **handle)
{
    if(!handle||!same_context(*handle))return YB_GPU_BACKEND_ARGUMENT;
    yb_gpu_ycc_backend *b=*handle;if(b->pending)return YB_GPU_BACKEND_BUSY;
    struct backend_gl *g=&b->gl;
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    b->closing=1;b->valid=0;
    for(unsigned i=0;i<1;i++)if(b->outputs[i]){
        g->DeleteTextures(1,&b->outputs[i]);
        if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
        b->outputs[i]=0;
    }
    for(unsigned i=0;i<1;i++)if(b->buffers[i]){
        g->DeleteBuffers(1,&b->buffers[i]);
        if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
        b->buffers[i]=0;
    }
    if(b->program){
        g->DeleteProgram(b->program);
        if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
        b->program=0;
    }
    free(b);*handle=NULL;return YB_GPU_BACKEND_OK;
}
int yb_gpu_ycc_abandon_destroyed_context(yb_gpu_ycc_backend **handle,uint32_t destroyed)
{
    if(!handle||!*handle||destroyed!=1||same_context(*handle))return YB_GPU_BACKEND_ARGUMENT;
    free(*handle);*handle=NULL;return YB_GPU_BACKEND_OK;
}
#else
struct yb_gpu_ycc_backend { int unused; };
int yb_gpu_ycc_create(const yb_gpu_ycc_create_info *info,yb_gpu_ycc_backend **output)
{(void)info;(void)output;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_ycc_submit(yb_gpu_ycc_backend *b,const yb_gpu_ycc_plan *p)
{(void)b;int status=yb_gpu_ycc_validate_plan(p);return status?status:YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_ycc_finish(yb_gpu_ycc_backend *b,uint64_t timeout,yb_gpu_ycc_output *output)
{(void)b;(void)timeout;(void)output;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_ycc_destroy(yb_gpu_ycc_backend **b)
{(void)b;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_ycc_abandon_destroyed_context(yb_gpu_ycc_backend **b,uint32_t destroyed)
{(void)b;(void)destroyed;return YB_GPU_BACKEND_UNSUPPORTED;}
#endif
