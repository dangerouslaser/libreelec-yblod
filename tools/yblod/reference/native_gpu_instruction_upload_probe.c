/* Actual backend injected-GL upload/dispatch tests; no GPU execution. */
#include <assert.h>
#include <stdio.h>
#include "native_gpu_composer_backend_libplacebo.c"

static yb_gpu_backend_plan plan;
static GLuint buffer,slot,next_texture=100;
static unsigned uploads,dispatches,ranges,uniform_count,uniform_calls,pending_wait,fence_fail;
static unsigned char storage[16384];
static size_t offset,range;
static float uniforms[256],legacy_uniforms[256];
static uintptr_t context(void *opaque){(void)opaque;return 1;}
static GLenum error(void){return GL_NO_ERROR;}
static void get_integer(GLenum name,GLint *value){assert(name==GL_MAX_TEXTURE_SIZE);*value=8192;}
static void get_indexed(GLenum name,GLuint index,GLint *value){(void)index;assert(name==GL_MAX_COMPUTE_WORK_GROUP_COUNT);*value=1024;}
static GLboolean is_texture(GLuint name){return name>=1&&name<=5?GL_TRUE:GL_FALSE;}
static void active_texture(GLenum name){slot=name-GL_TEXTURE0;}
static void bind_texture(GLenum target,GLuint name){assert(target==GL_TEXTURE_2D);(void)name;}
static void bind_sampler(GLuint unit,GLuint sampler){(void)unit;assert(!sampler);}
static void texture_level(GLenum target,GLint level,GLenum name,GLint *value)
{
    assert(target==GL_TEXTURE_2D&&!level&&slot<5);
    int half=slot==1||slot==2||slot==4;
    if(name==GL_TEXTURE_WIDTH)*value=(GLint)(half?plan.width/2:plan.width);
    else if(name==GL_TEXTURE_HEIGHT)*value=(GLint)(half?plan.height/2:plan.height);
    else {assert(name==GL_TEXTURE_INTERNAL_FORMAT);*value=slot==1||slot==4?GL_RG16:GL_R16;}
}
static void texture_parameter(GLenum target,GLenum name,GLint *value)
{
    assert(target==GL_TEXTURE_2D);
    if(name==GL_TEXTURE_BASE_LEVEL||name==GL_TEXTURE_MAX_LEVEL)*value=0;
    else if(name==GL_TEXTURE_MIN_FILTER)*value=GL_NEAREST;
    else {assert(name==GL_TEXTURE_SWIZZLE_RGBA);value[0]=GL_RED;value[1]=GL_GREEN;value[2]=GL_BLUE;value[3]=GL_ALPHA;}
}
static void bind_buffer(GLenum target,GLuint name){assert(target==GL_SHADER_STORAGE_BUFFER);buffer=name;}
static void upload(GLenum target,GLintptr start,GLsizeiptr bytes,const void *data)
{
    assert(target==GL_SHADER_STORAGE_BUFFER&&!start&&bytes>0);
    if(buffer==11){assert((size_t)bytes<=sizeof(storage));memcpy(storage,data,(size_t)bytes);uploads++;}
    else {assert(buffer==12&&bytes==4&&*(const uint32_t *)data==0);}
}
static void bind_base(GLenum target,GLuint index,GLuint name)
{assert(target==GL_SHADER_STORAGE_BUFFER);if(index==0){assert(name==11);offset=0;range=3352;}else assert(index==1&&name==12);}
static void bind_range(GLenum target,GLuint index,GLuint name,GLintptr start,GLsizeiptr bytes)
{assert(target==GL_SHADER_STORAGE_BUFFER&&!index&&name==11&&start>=0&&bytes==3352);offset=(size_t)start;range=(size_t)bytes;ranges++;}
static void use_program(GLuint program){assert(program==10);}
static void uniform3ui(GLint location,GLuint width,GLuint height,GLuint z)
{assert(!location&&width==plan.width&&height==plan.height&&!z);}
static void record_uniform(GLint location,GLsizei count,const GLfloat *values,unsigned components)
{assert(location>=0&&count>0);size_t n=(size_t)count*components;assert(uniform_count+n<=256);memcpy(uniforms+uniform_count,values,n*sizeof(float));uniform_count+=(unsigned)n;uniform_calls++;}
static void uniform1(GLint l,GLsizei n,const GLfloat *v){record_uniform(l,n,v,1);}
static void uniform3(GLint l,GLsizei n,const GLfloat *v){record_uniform(l,n,v,3);}
static void uniform4(GLint l,GLsizei n,const GLfloat *v){record_uniform(l,n,v,4);}
static void image(GLuint unit,GLuint texture,GLint level,GLboolean layered,GLint layer,GLenum access,GLenum format)
{assert(unit<3&&texture>=100&&!level&&!layered&&!layer&&access==GL_WRITE_ONLY&&format==GL_R16UI);}
static void dispatch(GLuint x,GLuint y,GLuint z)
{
    uint32_t component=dispatches%3;
    int64_t expected[419];pack_metadata(&plan,component,expected);
    assert(range==sizeof(expected)&&offset+range<=sizeof(storage));
    assert(!memcmp(storage+offset,expected,sizeof(expected)));
    uint32_t width=component?plan.width/2:plan.width,height=component?plan.height/2:plan.height;
    assert(x==(width+7)/8&&y==(height+7)/8&&z==1);dispatches++;
}
static void barrier(GLbitfield bits){assert(bits==(GL_SHADER_IMAGE_ACCESS_BARRIER_BIT|GL_TEXTURE_FETCH_BARRIER_BIT|GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT));}
static GLsync fence(GLenum condition,GLbitfield flags){assert(condition==GL_SYNC_GPU_COMMANDS_COMPLETE&&!flags);return fence_fail?NULL:(GLsync)(uintptr_t)1;}
static GLenum wait_sync(GLsync sync,GLbitfield flags,GLuint64 timeout)
{assert(sync==(GLsync)(uintptr_t)1&&flags==GL_SYNC_FLUSH_COMMANDS_BIT&&timeout==1000);return pending_wait?GL_TIMEOUT_EXPIRED:GL_ALREADY_SIGNALED;}
static void delete_sync(GLsync sync){assert(sync==(GLsync)(uintptr_t)1);}
static void read_buffer(GLenum target,GLintptr start,GLsizeiptr bytes,void *data)
{assert(target==GL_SHADER_STORAGE_BUFFER&&buffer==12&&!start&&bytes==4);*(uint32_t *)data=0;}
static void gen_textures(GLsizei count,GLuint *names){for(GLsizei i=0;i<count;i++)names[i]=next_texture++;}
static void delete_textures(GLsizei count,const GLuint *names){(void)count;(void)names;}
static void tex_parameter(GLenum target,GLenum name,GLint value){(void)name;(void)value;assert(target==GL_TEXTURE_2D);}
static void tex_storage(GLenum target,GLsizei levels,GLenum format,GLsizei w,GLsizei h){assert(target==GL_TEXTURE_2D&&levels==1&&format==GL_R16UI&&w>0&&h>0);}
static void initialize(yb_gpu_composer_backend *b,yb_gpu_fp32_instruction_stats *stats,int enabled)
{
    memset(b,0,sizeof(*b));b->context=1;b->owner.current_context=context;
    b->program=10;b->buffers[0]=11;b->buffers[1]=12;b->width=b->height=4;
    for(unsigned c=0;c<3;c++){b->outputs[c]=100+c;b->fp_topology[c][0]=2;b->fp_topology[c][2]=1;}
    b->fp_native_output=1;b->instruction_stats=stats;stats->version=1;stats->enabled=(uint32_t)enabled;
    struct backend_gl *g=&b->gl;
    g->GetError=error;g->GetIntegerv=get_integer;g->GetIntegeri_v=get_indexed;
    g->IsTexture=is_texture;g->ActiveTexture=active_texture;g->BindTexture=bind_texture;
    g->BindSampler=bind_sampler;g->GetTexLevelParameteriv=texture_level;g->GetTexParameteriv=texture_parameter;
    g->BindBuffer=bind_buffer;g->BufferSubData=upload;g->BindBufferBase=bind_base;g->BindBufferRange=bind_range;
    g->UseProgram=use_program;g->Uniform3ui=uniform3ui;g->Uniform1fv=uniform1;g->Uniform3fv=uniform3;g->Uniform4fv=uniform4;
    g->BindImageTexture=image;g->DispatchCompute=dispatch;g->MemoryBarrier=barrier;g->FenceSync=fence;
    g->ClientWaitSync=wait_sync;g->DeleteSync=delete_sync;g->GetBufferSubData=read_buffer;
    g->GenTextures=gen_textures;g->DeleteTextures=delete_textures;g->TexParameteri=tex_parameter;g->TexStorage2D=tex_storage;
    if(enabled){assert(instruction_layout(256,&b->instruction_stride,&b->instruction_bytes));b->instruction_words=calloc(b->instruction_bytes/8,8);assert(b->instruction_words);}
    uploads=dispatches=ranges=uniform_count=uniform_calls=pending_wait=fence_fail=0;memset(storage,0,sizeof(storage));
}
static void set_plan(void)
{
    memset(&plan,0,sizeof(plan));plan.version=1;plan.width=plan.height=4;plan.input_format=1;
    plan.enhancement_enabled=1;plan.output_depth=12;plan.mapping.bit_depth=10;plan.mapping.denominator=16;
    for(unsigned i=0;i<5;i++)plan.textures[i]=i+1;
    plan.frame_id[0]=plan.guide_frame_id[0]=plan.enhancement_frame_id[0]=1;
    plan.guide_contract_id[0]=2;plan.enhancement_scale_contract_id[0]=3;
    for(unsigned c=0;c<3;c++){
        struct yb_component_mapping *curve=&plan.mapping.components[c];
        curve->pivot_count=2;curve->pivots[1]=1023;curve->segments[0].method=YB_POLYNOMIAL;
        curve->segments[0].order=1;curve->segments[0].coefficients[0][1]=65536;
        plan.nlq[c].bit_depth=10;plan.nlq[c].denominator=16;plan.nlq[c].offset=512;
    }
    assert(yb_gpu_backend_validate_plan(&plan)==YB_GPU_BACKEND_OK);
}
int main(void)
{
    unsigned layouts=0;
    for(GLint alignment=1;alignment<=65536;alignment++){
        size_t stride=0,total=0;assert(instruction_layout(alignment,&stride,&total));
        assert(stride%((size_t)alignment)==0&&stride%8==0&&stride>=3352&&total==stride*3&&total<=1572864);layouts++;
    }
    size_t stride=7,total=9;assert(!instruction_layout(0,&stride,&total)&&stride==7&&total==9);
    assert(!instruction_layout(65537,&stride,&total));
    unsigned legacy_count=0;
    for(int enabled=0;enabled<=1;enabled++){
        set_plan();yb_gpu_composer_backend b;yb_gpu_fp32_instruction_stats stats={0};initialize(&b,&stats,enabled);
        int status=yb_gpu_backend_submit(&b,&plan);
        if(status)fprintf(stderr,"initial submit enabled=%d status=%d\n",enabled,status);
        assert(status==YB_GPU_BACKEND_OK);
        assert(uploads==(enabled?1U:3U)&&dispatches==3&&ranges==(enabled?3U:0U));
        if(!enabled){legacy_count=uniform_count;memcpy(legacy_uniforms,uniforms,sizeof(uniforms));}
        else assert(uniform_count==legacy_count&&!memcmp(legacy_uniforms,uniforms,uniform_count*sizeof(float)));
        unsigned saved_uploads=uploads;assert(yb_gpu_backend_submit(&b,&plan)==YB_GPU_BACKEND_BUSY&&uploads==saved_uploads);
        yb_gpu_backend_output out,sentinel;memset(&out,0xa5,sizeof(out));sentinel=out;
        pending_wait=1;assert(yb_gpu_backend_finish(&b,1000,&out)==YB_GPU_BACKEND_PENDING&&!memcmp(&out,&sentinel,sizeof(out)));
        pending_wait=0;assert(yb_gpu_backend_finish(&b,1000,&out)==YB_GPU_BACKEND_OK);
        plan.mapping.components[1].segments[0].coefficients[0][1]=65535;plan.width=8;plan.height=6;
        status=yb_gpu_backend_submit(&b,&plan);
        if(status)fprintf(stderr,"resize submit enabled=%d status=%d validated=%d topology=%d\n",enabled,status,yb_gpu_backend_validate_plan(&plan),fp_same_topology(&b,&plan));
        assert(status==YB_GPU_BACKEND_OK);
        assert(yb_gpu_backend_finish(&b,1000,&out)==YB_GPU_BACKEND_OK&&out.width==8&&out.height==6);
        assert(stats.accepted_frames==2&&stats.metadata_uploads==(enabled?2U:6U)&&stats.range_bindings==(enabled?6U:0U)&&stats.dispatches==6);
        fence_fail=1;assert(yb_gpu_backend_submit(&b,&plan)==YB_GPU_BACKEND_GL_FAILURE&&b.pending&&b.failed);
        assert(stats.accepted_frames==2);free(b.instruction_words);
    }
    printf("{\"schema\":\"yblod.immutable-instructions-host-probe.v1\",\"complete\":true,\"alignment_cases\":%u,\"all_419_words_exact\":true,\"fp32_uniforms_bitwise_equal\":true,\"pending_reuse_rejected\":true,\"resize_and_coefficient_update\":true,\"failed_fence_retained\":true,\"gpu_execution\":false}\n",layouts);
    return 0;
}
