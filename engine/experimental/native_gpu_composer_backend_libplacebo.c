#include "native_gpu_composer_backend.h"
#include "native_gpu_guard.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

enum { BACKEND_WORDS=419 };
static int nonzero(const uint8_t token[32])
{ unsigned value=0;for(unsigned i=0;i<32;i++)value|=token[i];return value!=0; }
uint32_t yb_gpu_backend_abi_version(void) { return 1; }

int yb_gpu_backend_validate_plan(const yb_gpu_backend_plan *p)
{
    if(!p||(uintptr_t)p%_Alignof(yb_gpu_backend_plan)||p->version!=1||
       !p->width||!p->height||p->width>3840||p->height>2160||
       ((p->width|p->height)&1U)||(p->output_depth!=10&&p->output_depth!=12)||
       (p->enhancement_enabled!=0&&p->enhancement_enabled!=1))return YB_GPU_BACKEND_ARGUMENT;
    if(yb_validate_mapping(&p->mapping))return YB_GPU_BACKEND_METADATA;
    for(unsigned c=0;c<3;c++){
        const struct yb_nlq_config *n=&p->nlq[c];
        if(p->enhancement_enabled){
            if(yb_validate_nlq(n)||n->denominator!=p->mapping.denominator)return YB_GPU_BACKEND_METADATA;
        }else if(n->bit_depth||n->denominator||n->offset||n->slope||n->threshold||n->maximum)
            return YB_GPU_BACKEND_METADATA;
    }
    if(p->input_format!=YB_GPU_INPUT_NORMALIZED_P010_WHOLE_GUIDE10||
       !nonzero(p->frame_id)||!nonzero(p->guide_contract_id)||
       memcmp(p->frame_id,p->guide_frame_id,32))return YB_GPU_BACKEND_ARGUMENT;
    if(p->enhancement_enabled&&(!nonzero(p->enhancement_scale_contract_id)||
       memcmp(p->frame_id,p->enhancement_frame_id,32)))return YB_GPU_BACKEND_ARGUMENT;
    unsigned inputs=p->enhancement_enabled?5U:3U;
    for(unsigned i=0;i<inputs;i++){
        if(!p->textures[i])return YB_GPU_BACKEND_ARGUMENT;
        for(unsigned j=0;j<i;j++)if(p->textures[i]==p->textures[j])return YB_GPU_BACKEND_ARGUMENT;
    }
    struct yb_gpu_width_report width;
    if(yb_gpu_check_mapping_width(&p->mapping,&width))return YB_GPU_BACKEND_METADATA;
    int supported=p->enhancement_enabled==1&&p->mapping.bit_depth==10&&width.supported;
    for(unsigned c=0;c<3;c++)if(p->nlq[c].bit_depth!=10)supported=0;
    for(int32_t s=0;s<p->mapping.components[0].pivot_count-1;s++)
        if(p->mapping.components[0].segments[s].method!=YB_POLYNOMIAL)supported=0;
    return supported?YB_GPU_BACKEND_OK:YB_GPU_BACKEND_UNSUPPORTED;
}

static void pack_metadata(const yb_gpu_backend_plan *p,uint32_t c,int64_t words[BACKEND_WORDS])
{
    memset(words,0,sizeof(int64_t)*BACKEND_WORDS);
    const struct yb_component_mapping *curve=&p->mapping.components[c];
    const struct yb_nlq_config *n=&p->nlq[c];
    words[0]=(int64_t)p->width*p->height/(c?4:1);words[1]=c;
    words[2]=p->enhancement_enabled;words[3]=p->output_depth;
    words[4]=p->mapping.bit_depth;words[5]=p->mapping.denominator;
    words[6]=n->bit_depth;words[7]=n->offset;
    words[8]=(int64_t)n->slope;words[9]=(int64_t)n->threshold;words[10]=(int64_t)n->maximum;
    for(unsigned i=0;i<3;i++){
        const struct yb_component_mapping *bounds=&p->mapping.components[i];
        words[11+i*2]=bounds->pivots[0];words[12+i*2]=bounds->pivots[bounds->pivot_count-1];
    }
    words[17]=curve->pivot_count;
    for(int32_t i=0;i<curve->pivot_count;i++)words[18+i]=curve->pivots[i];
    for(int32_t s=0;s<curve->pivot_count-1;s++){
        words[35+s*24]=curve->segments[s].method;words[36+s*24]=curve->segments[s].order;
        words[37+s*24]=curve->segments[s].constant;
        const struct yb_segment *segment=&curve->segments[s];
        if(segment->method==YB_POLYNOMIAL){
            for(int32_t t=0;t<=segment->order;t++)words[38+s*24+t]=segment->coefficients[0][t];
        }else{
            for(int32_t r=0;r<segment->order;r++)for(int32_t t=0;t<7;t++)
                words[38+s*24+r*7+t]=segment->coefficients[r][t];
        }
    }
}

int yb_gpu_backend_pack_metadata(const yb_gpu_backend_plan *p,uint32_t c,int64_t words[BACKEND_WORDS])
{
    if(!p||!words||c>2||(uintptr_t)words%_Alignof(int64_t))return YB_GPU_BACKEND_ARGUMENT;
    uintptr_t a=(uintptr_t)p,b=(uintptr_t)words;
    if(a>UINTPTR_MAX-sizeof(*p)||b>UINTPTR_MAX-sizeof(int64_t)*BACKEND_WORDS||
       (a<b+sizeof(int64_t)*BACKEND_WORDS&&b<a+sizeof(*p)))return YB_GPU_BACKEND_ARGUMENT;
    int status=yb_gpu_backend_validate_plan(p);if(status)return status;
    int64_t local[BACKEND_WORDS];pack_metadata(p,c,local);
    memcpy(words,local,sizeof(local));return YB_GPU_BACKEND_OK;
}

#ifndef YB_GPU_BACKEND_HOST_ONLY
#include <GL/glcorearb.h>
#include <math.h>
#include <stdio.h>
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
 X(BindImageTexture,PFNGLBINDIMAGETEXTUREPROC) X(Uniform3ui,PFNGLUNIFORM3UIPROC) \
 X(GetUniformLocation,PFNGLGETUNIFORMLOCATIONPROC) X(Uniform1fv,PFNGLUNIFORM1FVPROC) \
 X(Uniform3fv,PFNGLUNIFORM3FVPROC) X(Uniform4fv,PFNGLUNIFORM4FVPROC) \
 X(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC) X(MemoryBarrier,PFNGLMEMORYBARRIERPROC) \
 X(FenceSync,PFNGLFENCESYNCPROC) X(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC) X(DeleteSync,PFNGLDELETESYNCPROC)
#define DECLARE(field,type) type field;
struct backend_gl { GL_PROCS(DECLARE) };
#undef DECLARE
struct yb_gpu_composer_backend {
    struct backend_gl gl;
    yb_gpu_backend_create_info owner;
    uintptr_t context;
    GLuint program,buffers[2],outputs[3];
    GLsync fence;
    uint32_t width,height,output_depth;
    uint8_t frame_id[32];
    int pending,valid,failed,closing;
    int fp_topology[3][17],fp_native_output;
    GLint fp_locations[3][5],fp_input_locations[2];
};
/* Experimental copy only: same public ABI/lifetime/fences as canonical.
 * Shader topology is bounded, parsed once, then checked before any submit GL
 * state/output mutation. Numerical coefficients are decoded once per dispatch
 * on the CPU and uploaded as floats, never converted per pixel. */
static int fp_manifest_values(const char *p,int *values,unsigned count)
{
    for(unsigned i=0;i<count;i++) {
        while(*p==' '||*p=='\t')p++;
        if(*p<'0'||*p>'9')return 0;
        unsigned value=0;
        do {
            value=value*10U+(unsigned)(*p-'0');
            if(value>9U)return 0;
            p++;
        } while(*p>='0'&&*p<='9');
        if(*p!=' '&&*p!='\t'&&*p!='\n'&&*p!=0)return 0;
        values[i]=(int)value;
    }
    while(*p==' '||*p=='\t')p++;
    return *p=='\n'||*p==0;
}
static int fp_parse_shader(yb_gpu_composer_backend *b,const yb_gpu_backend_create_info *info)
{
    char *text=malloc(info->shader_bytes+1);
    if(!text)return 0;
    memcpy(text,info->shader_source,info->shader_bytes);text[info->shader_bytes]=0;
    const char *mode=strstr(text,"// YB_FP_OUTPUT_RANGE_NATIVE ");
    int good=mode&&fp_manifest_values(mode+strlen("// YB_FP_OUTPUT_RANGE_NATIVE "),&b->fp_native_output,1)&&
        (b->fp_native_output==0||b->fp_native_output==1);
    if(mode&&strstr(mode+1,"// YB_FP_OUTPUT_RANGE_NATIVE "))good=0;
    for(int c=0;c<3&&good;c++) {
        char marker[64];int *t=b->fp_topology[c];
        int n=snprintf(marker,sizeof(marker),"// YB_FP_TOPOLOGY %d ",c);
        const char *p=n>0&&(size_t)n<sizeof(marker)?strstr(text,marker):NULL;
        if(!p||strstr(p+1,marker)||!fp_manifest_values(p+(size_t)n,t,17)||
           t[0]<2||t[0]>9){good=0;break;}
        for(int s=0;s<8;s++) {
            int method=t[1+s*2],order=t[2+s*2];
            if(s<t[0]-1) {
                if(method<0||method>1||order<1||order>(method?3:2))good=0;
            } else if(method||order)good=0;
        }
    }
    free(text);return good;
}
static int fp_same_topology(const yb_gpu_composer_backend *b,const yb_gpu_backend_plan *p)
{
    if(p->mapping.bit_depth!=10||p->mapping.denominator<1||p->mapping.denominator>32)return 0;
    for(int c=0;c<3;c++) {
        const struct yb_component_mapping *curve=&p->mapping.components[c];
        const int *t=b->fp_topology[c];
        if(curve->pivot_count!=t[0])return 0;
        for(int s=0;s<curve->pivot_count-1;s++)
            if(curve->segments[s].method!=t[1+s*2]||curve->segments[s].order!=t[2+s*2])return 0;
    }
    return 1;
}
static int fp_cache_locations(yb_gpu_composer_backend *b)
{
    const char *roles[5]={"pivots","coeffs","mmr","lo","hi"};
    for(int c=0;c<3;c++) {
        int has_mmr=0;
        for(int s=0;s<b->fp_topology[c][0]-1;s++)if(b->fp_topology[c][1+s*2])has_mmr=1;
        for(int role=0;role<5;role++) {
            char name[64];int n=snprintf(name,sizeof(name),"yb_fp_c%d_%s",c,roles[role]);
            if(n<1||(size_t)n>=sizeof(name))return 0;
            b->fp_locations[c][role]=b->gl.GetUniformLocation(b->program,name);
            if((role!=0||b->fp_topology[c][0]>2)&&(role!=2||has_mmr)&&b->fp_locations[c][role]<0)return 0;
        }
    }
    b->fp_input_locations[0]=b->gl.GetUniformLocation(b->program,"yb_fp_input_lo");
    b->fp_input_locations[1]=b->gl.GetUniformLocation(b->program,"yb_fp_input_hi");
    return b->fp_input_locations[0]>=0&&b->fp_input_locations[1]>=0&&b->gl.GetError()==GL_NO_ERROR;
}
static void fp_upload(yb_gpu_composer_backend *b,uint32_t c,const int64_t words[BACKEND_WORDS])
{
    float pivots[7],coeffs[8][4]={{0}},mmr[48][4]={{0}},input_lo[3],input_hi[3];
    int pc=(int)words[17],packed=0;
    for(int i=0;i<7;i++)pivots[i]=i<pc-2?(float)words[19+i]/1024.0f:1e9f;
    for(int i=0;i<3;i++){input_lo[i]=(float)words[11+i*2];input_hi[i]=(float)words[12+i*2];}
    for(int s=0;s<pc-1;s++) {
        int offset=35+s*24,order=(int)words[offset+1];
        if(words[offset]==0) {
            for(int k=0;k<=order;k++)coeffs[s][k]=(float)ldexp((double)words[offset+3+k],-(int)words[5]);
        } else {
            coeffs[s][0]=(float)ldexp((double)words[offset+2],-(int)words[5]);
            coeffs[s][1]=(float)packed;coeffs[s][3]=(float)order;
            for(int r=0;r<order;r++)for(int group=0;group<2;group++) {
                for(int k=0;k<4;k++)if(group||k!=3)
                    mmr[packed][k]=(float)ldexp((double)words[offset+3+r*7+(group?3+k:k)],-(int)words[5]);
                packed++;
            }
        }
    }
    float low=b->fp_native_output?0.0f:(float)words[18]/1024.0f;
    float high=b->fp_native_output?1.0f:(float)words[18+pc-1]/1024.0f;
    struct backend_gl *g=&b->gl;const GLint *loc=b->fp_locations[c];
    if(pc>2)g->Uniform1fv(loc[0],7,pivots);
    g->Uniform4fv(loc[1],pc>2?8:1,&coeffs[0][0]);
    if(packed)g->Uniform4fv(loc[2],packed,&mmr[0][0]);
    g->Uniform1fv(loc[3],1,&low);g->Uniform1fv(loc[4],1,&high);
    g->Uniform3fv(b->fp_input_locations[0],1,input_lo);g->Uniform3fv(b->fp_input_locations[1],1,input_hi);
}
static int same_context(const yb_gpu_composer_backend *b)
{return b&&b->owner.current_context&&b->owner.current_context(b->owner.opaque)==b->context;}
static int software_renderer(const char *name)
{
    if(!name)return 1;
    char lower[4096];size_t n=strlen(name);if(n>=sizeof(lower))return 1;
    for(size_t i=0;i<=n;i++)lower[i]=(char)tolower((unsigned char)name[i]);
    return strstr(lower,"llvmpipe")||strstr(lower,"softpipe")||strstr(lower,"software")||strstr(lower,"swrast");
}
static void delete_owned(yb_gpu_composer_backend *b)
{
    b->gl.DeleteTextures(3,b->outputs);b->gl.DeleteBuffers(2,b->buffers);
    if(b->program)b->gl.DeleteProgram(b->program);
}

int yb_gpu_backend_create(const yb_gpu_backend_create_info *info,yb_gpu_composer_backend **output)
{
    if(!info||!output||*output||!info->get_proc||!info->current_context||info->version!=1||
       !info->shader_source||!info->shader_bytes||info->shader_bytes>65536||
       memchr(info->shader_source,0,info->shader_bytes))return YB_GPU_BACKEND_ARGUMENT;
    uintptr_t context=info->current_context(info->opaque);if(!context)return YB_GPU_BACKEND_ARGUMENT;
    const uint16_t endian=1;if(*(const uint8_t *)&endian!=1)return YB_GPU_BACKEND_UNSUPPORTED;
    yb_gpu_composer_backend *b=calloc(1,sizeof(*b));if(!b)return YB_GPU_BACKEND_GL_FAILURE;
    b->owner=*info;b->context=context;
    if(!fp_parse_shader(b,info)){free(b);return YB_GPU_BACKEND_METADATA;}
#define LOAD(field,type) b->gl.field=(type)info->get_proc("gl" #field,info->opaque);if(!b->gl.field){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
    GL_PROCS(LOAD)
#undef LOAD
    struct backend_gl *g=&b->gl;
    GLint major=0,minor=0,extensions=0;
    if(g->GetError()!=GL_NO_ERROR){free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    g->GetIntegerv(GL_MAJOR_VERSION,&major);g->GetIntegerv(GL_MINOR_VERSION,&minor);g->GetIntegerv(GL_NUM_EXTENSIONS,&extensions);
    int supported=0;
    if(major<4||(major==4&&minor<3)||extensions<0||extensions>8192||
       software_renderer((const char *)g->GetString(GL_RENDERER))){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
    for(GLint i=0;i<extensions;i++){
        const char *name=(const char *)g->GetStringi(GL_EXTENSIONS,(GLuint)i);
        if(name&&!strcmp(name,"GL_ARB_gpu_shader_int64"))supported=1;
    }
    GLint units=0,images=0,invocations=0,sx=0,sy=0;
    g->GetIntegerv(GL_MAX_COMPUTE_TEXTURE_IMAGE_UNITS,&units);g->GetIntegerv(GL_MAX_COMPUTE_IMAGE_UNIFORMS,&images);
    g->GetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,&invocations);
    g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,0,&sx);g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,1,&sy);
    if(!supported||units<5||images<3||invocations<64||sx<8||sy<8||g->GetError()!=GL_NO_ERROR){free(b);return YB_GPU_BACKEND_UNSUPPORTED;}
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
    if(!fp_cache_locations(b)){g->DeleteProgram(b->program);free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    g->GenBuffers(2,b->buffers);
    for(unsigned i=0;i<2;i++){
        if(!b->buffers[i]){delete_owned(b);free(b);return YB_GPU_BACKEND_GL_FAILURE;}
        g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[i]);
        g->BufferData(GL_SHADER_STORAGE_BUFFER,i?4:(GLsizeiptr)(BACKEND_WORDS*sizeof(int64_t)),NULL,GL_DYNAMIC_COPY);
    }
    if(g->GetError()!=GL_NO_ERROR){delete_owned(b);free(b);return YB_GPU_BACKEND_GL_FAILURE;}
    *output=b;return YB_GPU_BACKEND_OK;
}

static int validate_texture(yb_gpu_composer_backend *b,const yb_gpu_backend_plan *p,unsigned slot)
{
    struct backend_gl *g=&b->gl;
    int pair=slot==1||slot==4,half=slot==1||slot==2||slot==4;
    if(!g->IsTexture(p->textures[slot]))return 0;
    for(unsigned i=0;i<3;i++)if(p->textures[slot]==b->outputs[i])return 0;
    g->ActiveTexture(GL_TEXTURE0+slot);g->BindTexture(GL_TEXTURE_2D,p->textures[slot]);g->BindSampler(slot,0);
    GLint width=0,height=0,format=0,base=0,max=0,min_filter=0,swizzle[4]={0,0,0,0};
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
    g->GetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,&base);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,&max);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,&min_filter);
    g->GetTexParameteriv(GL_TEXTURE_2D,GL_TEXTURE_SWIZZLE_RGBA,swizzle);
    return width==(GLint)(half?p->width/2U:p->width)&&height==(GLint)(half?p->height/2U:p->height)&&
       format==(pair?GL_RG16:GL_R16)&&base==0&&max>=0&&
       (max==0||min_filter==GL_NEAREST||min_filter==GL_LINEAR)&&
       swizzle[0]==GL_RED&&swizzle[1]==GL_GREEN&&swizzle[2]==GL_BLUE&&swizzle[3]==GL_ALPHA&&g->GetError()==GL_NO_ERROR;
}

int yb_gpu_backend_submit(yb_gpu_composer_backend *b,const yb_gpu_backend_plan *p)
{
    int status=yb_gpu_backend_validate_plan(p);if(status)return status;
    if(!same_context(b))return YB_GPU_BACKEND_ARGUMENT;
    if(b->pending||b->closing)return YB_GPU_BACKEND_BUSY;
    if(!fp_same_topology(b,p))return YB_GPU_BACKEND_METADATA;
    struct backend_gl *g=&b->gl;
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    GLint limit=0,gx=0,gy=0;
    g->GetIntegerv(GL_MAX_TEXTURE_SIZE,&limit);
    g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,0,&gx);g->GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,1,&gy);
    if(limit<(GLint)p->width||limit<(GLint)p->height||gx<(GLint)((p->width+7U)/8U)||gy<(GLint)((p->height+7U)/8U))return YB_GPU_BACKEND_UNSUPPORTED;
    for(unsigned slot=0;slot<5;slot++)if(!validate_texture(b,p,slot))return YB_GPU_BACKEND_UNSUPPORTED;
    int resize=b->width!=p->width||b->height!=p->height;
    GLuint fresh[3]={0,0,0};
    if(resize){
        g->GenTextures(3,fresh);
        for(unsigned c=0;c<3;c++){
            if(!fresh[c]){g->DeleteTextures(3,fresh);return YB_GPU_BACKEND_GL_FAILURE;}
            g->ActiveTexture(GL_TEXTURE5);g->BindTexture(GL_TEXTURE_2D,fresh[c]);
            g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);g->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
            g->TexStorage2D(GL_TEXTURE_2D,1,GL_R16UI,(GLsizei)(c?p->width/2U:p->width),(GLsizei)(c?p->height/2U:p->height));
        }
        if(g->GetError()!=GL_NO_ERROR){g->DeleteTextures(3,fresh);return YB_GPU_BACKEND_GL_FAILURE;}
    }
    b->valid=0;b->failed=0;
    const uint32_t zero=0;
    g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[1]);g->BufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&zero);
    g->BindBufferBase(GL_SHADER_STORAGE_BUFFER,1,b->buffers[1]);
    g->UseProgram(b->program);g->Uniform3ui(0,p->width,p->height,0);
    for(unsigned c=0;c<3;c++)g->BindImageTexture(c,resize?fresh[c]:b->outputs[c],0,GL_FALSE,0,GL_WRITE_ONLY,GL_R16UI);
    for(uint32_t c=0;c<3;c++){
        int64_t words[BACKEND_WORDS];pack_metadata(p,c,words);
        fp_upload(b,c,words);
        g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[0]);g->BufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(words),words);
        g->BindBufferBase(GL_SHADER_STORAGE_BUFFER,0,b->buffers[0]);
        uint32_t width=c?p->width/2U:p->width,height=c?p->height/2U:p->height;
        g->DispatchCompute((width+7U)/8U,(height+7U)/8U,1);
    }
    g->MemoryBarrier(GL_SHADER_IMAGE_ACCESS_BARRIER_BIT|GL_TEXTURE_FETCH_BARRIER_BIT|GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
    b->fence=g->FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    /* Even if a GL error occurs after queueing, retain pending work so caller
     * cannot recycle borrowed inputs before completion. */
    if(resize){g->DeleteTextures(3,b->outputs);memcpy(b->outputs,fresh,sizeof(fresh));}
    b->width=p->width;b->height=p->height;b->output_depth=(uint32_t)p->output_depth;memcpy(b->frame_id,p->frame_id,32);
    b->pending=1;
    if(!b->fence||g->GetError()!=GL_NO_ERROR){b->failed=1;return YB_GPU_BACKEND_GL_FAILURE;}
    return YB_GPU_BACKEND_OK;
}

int yb_gpu_backend_finish(yb_gpu_composer_backend *b,uint64_t timeout,yb_gpu_backend_output *output)
{
    if(!output||(uintptr_t)output%_Alignof(yb_gpu_backend_output)||timeout>UINT64_C(5000000000)||!same_context(b))return YB_GPU_BACKEND_ARGUMENT;
    if(!b->pending)return YB_GPU_BACKEND_ARGUMENT;
    if(!b->fence)return YB_GPU_BACKEND_GL_FAILURE;
    struct backend_gl *g=&b->gl;
    GLenum waited=g->ClientWaitSync(b->fence,GL_SYNC_FLUSH_COMMANDS_BIT,timeout);
    if(waited==GL_TIMEOUT_EXPIRED)return YB_GPU_BACKEND_PENDING;
    if((waited!=GL_ALREADY_SIGNALED&&waited!=GL_CONDITION_SATISFIED)||g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    g->DeleteSync(b->fence);b->fence=NULL;b->pending=0;
    if(b->failed)return YB_GPU_BACKEND_GL_FAILURE;
    uint32_t error=UINT32_MAX;
    g->BindBuffer(GL_SHADER_STORAGE_BUFFER,b->buffers[1]);g->GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&error);
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    if(error)return YB_GPU_BACKEND_FRAME_REJECTED;
    yb_gpu_backend_output value={0};value.version=1;value.width=b->width;value.height=b->height;value.output_depth=b->output_depth;
    memcpy(value.textures,b->outputs,sizeof(value.textures));memcpy(value.frame_id,b->frame_id,32);
    b->valid=1;*output=value;return YB_GPU_BACKEND_OK;
}

int yb_gpu_backend_destroy(yb_gpu_composer_backend **handle)
{
    if(!handle||!same_context(*handle))return YB_GPU_BACKEND_ARGUMENT;
    yb_gpu_composer_backend *b=*handle;if(b->pending)return YB_GPU_BACKEND_BUSY;
    struct backend_gl *g=&b->gl;
    if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
    b->closing=1;b->valid=0;
    for(unsigned i=0;i<3;i++)if(b->outputs[i]){
        g->DeleteTextures(1,&b->outputs[i]);
        if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;
        b->outputs[i]=0;
    }
    for(unsigned i=0;i<2;i++)if(b->buffers[i]){
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
int yb_gpu_backend_abandon_destroyed_context(yb_gpu_composer_backend **handle,uint32_t destroyed)
{
    if(!handle||!*handle||destroyed!=1||same_context(*handle))return YB_GPU_BACKEND_ARGUMENT;
    free(*handle);*handle=NULL;return YB_GPU_BACKEND_OK;
}
#else
struct yb_gpu_composer_backend { int unused; };
int yb_gpu_backend_create(const yb_gpu_backend_create_info *info,yb_gpu_composer_backend **output)
{(void)info;(void)output;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_backend_submit(yb_gpu_composer_backend *b,const yb_gpu_backend_plan *p)
{(void)b;int status=yb_gpu_backend_validate_plan(p);return status?status:YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_backend_finish(yb_gpu_composer_backend *b,uint64_t timeout,yb_gpu_backend_output *output)
{(void)b;(void)timeout;(void)output;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_backend_destroy(yb_gpu_composer_backend **b)
{(void)b;return YB_GPU_BACKEND_UNSUPPORTED;}
int yb_gpu_backend_abandon_destroyed_context(yb_gpu_composer_backend **b,uint32_t destroyed)
{(void)b;(void)destroyed;return YB_GPU_BACKEND_UNSUPPORTED;}
#endif
