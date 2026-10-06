#define _GNU_SOURCE
#include "native_libplacebo_reshape.h"
/* Diagnostic, metadata-specialized BL reshape generator. Actual libplacebo
 * generated code; not a hand-written FP32 composer. Native NLQ stays separate.
 * Input: three canonical 419-word little-endian signed metadata blocks.
 * Output: GLSL fragment for a dedicated experimental compute shader.
 * No films, RPU payloads, textures, GPU contexts or production state handled. */
#include <libplacebo/shaders/colorspace.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { WORDS=419, COMPONENTS=3 };
static int convert(const int64_t metadata[3][419],int c,struct pl_dovi_metadata *d)
{
    const int64_t *m=metadata[c];
    if(m[1]!=c||m[4]!=10||m[5]<1||m[5]>32||m[17]<2||m[17]>9)return 0;
    for(int k=0;k<3;k++) {
        if(m[11+k*2]<0||m[12+k*2]>1023||m[11+k*2]>=m[12+k*2])return 0;
        if(m[11+k*2]!=metadata[k][18] ||
           m[12+k*2]!=metadata[k][18+metadata[k][17]-1])return 0;
    }
    struct pl_reshape_data *curve=&d->comp[c];
    curve->num_pivots=(uint8_t)m[17];
    for(int i=0;i<m[17];i++) {
        if(m[18+i]<0||m[18+i]>1023||(i&&m[18+i]<=m[17+i]))return 0;
        /* Deliberately preserve our /2^depth feature domain, NOT upstream
         * pl_map_dovi_metadata's /(2^depth-1) default. Both pivots and samples
         * use the same exactly representable binary scaling. */
        curve->pivots[i]=(float)m[18+i]/1024.0f;
    }
    for(int s=0;s<m[17]-1;s++) {
        int offset=35+s*24;
        int64_t method=m[offset],order=m[offset+1];
        if(method<0||method>1||order<1||order>(method?3:2))return 0;
        curve->method[s]=(uint8_t)method;
        if(!method) {
            for(int j=0;j<=order;j++)curve->poly_coeffs[s][j]=
                (float)ldexp((double)m[offset+3+j],-(int)m[5]);
        } else {
            curve->mmr_order[s]=(uint8_t)order;
            curve->mmr_constant[s]=(float)ldexp((double)m[offset+2],-(int)m[5]);
            for(int r=0;r<order;r++)for(int j=0;j<7;j++)
                curve->mmr_coeffs[s][r][j]=
                    (float)ldexp((double)m[offset+3+r*7+j],-(int)m[5]);
        }
    }
    return 1;
}
static int emit_float(FILE *output,float f)
{
    if(!isfinite(f))return 0;
    char text[64];int n=snprintf(text,sizeof(text),"%.9g",(double)f);
    if(n<0||(size_t)n>=sizeof(text))return 0;
    fputs(text,output);
    if(!strchr(text,'.')&&!strchr(text,'e')&&!strchr(text,'E'))fputs(".0",output);
    return 1;
}
static int emit_variables(FILE *output,const struct pl_shader_res *r)
{
    for(int i=0;i<r->num_variables;i++) {
        const struct pl_shader_var *v=&r->variables[i];
        if(v->var.type!=PL_VAR_FLOAT||v->var.dim_m!=1||
           v->var.dim_v<1||v->var.dim_v>4||v->var.dim_a<1||v->var.dim_a>48||!v->data)return 0;
        const char *type=v->var.dim_v==1?"float":v->var.dim_v==2?"vec2":v->var.dim_v==3?"vec3":"vec4";
        fprintf(output,"const %s %s",type,v->var.name);
        if(v->var.dim_a>1)fprintf(output,"[%d]",v->var.dim_a);
        fprintf(output," = ");
        if(v->var.dim_a>1)fprintf(output,"%s[%d](",type,v->var.dim_a);
        const float *data=v->data;
        for(int a=0;a<v->var.dim_a;a++) {
            if(a)fprintf(output,",");
            if(v->var.dim_v>1)fprintf(output,"%s(",type);
            for(int k=0;k<v->var.dim_v;k++) {
                if(k)fprintf(output,",");
                if(!emit_float(output,data[a*v->var.dim_v+k]))return 0;
            }
            if(v->var.dim_v>1)fprintf(output,")");
        }
        if(v->var.dim_a>1)fprintf(output,")");
        fprintf(output,";\n");
    }
    return 1;
}
/* Runtime numerical metadata variant: generated function text is untouched.
 * Mutable globals are private to each shader invocation, not shared state.
 * Topology remains specialized as upstream generation specializes topology. */
static int emit_runtime_variables(FILE *output,const int64_t metadata[3][419],const struct pl_shader_res *r,int c)
{
    const int64_t *m=metadata[c];int pc=(int)m[17],segments=pc-1;
    int has_mmr=0,packed=0;
    for(int s=0;s<segments;s++)if(m[35+s*24]) {
        has_mmr=1;packed+=2*(int)m[36+s*24];
    }
    int expected=3+(pc>2?1:0)+(has_mmr?1:0);
    if(r->num_variables!=expected)return 0;
    for(int i=0;i<r->num_variables;i++) {
        const struct pl_shader_var *v=&r->variables[i];
        if(v->var.type!=PL_VAR_FLOAT||v->var.dim_m!=1||v->var.dim_a<1||
           v->var.dim_a>48||(v->var.dim_v!=1&&v->var.dim_v!=4))return 0;
        fprintf(output,"%s %s",v->var.dim_v==1?"float":"vec4",v->var.name);
        if(v->var.dim_a>1)fprintf(output,"[%d]",v->var.dim_a);
        fprintf(output,";\n");
    }
    fprintf(output,"void yb_libplacebo_init_%d() {\nfloat coefficient_scale=exp2(-float(m[5]));\n",c);
    int at=0;
    if(pc>2) {
        const struct pl_shader_var *p=&r->variables[at++];
        if(p->var.dim_v!=1||p->var.dim_a!=7)return 0;
        for(int i=0;i<7;i++) {
            fprintf(output,"%s[%d] = ",p->var.name,i);
            if(i<pc-2)fprintf(output,"float(m[%d])/1024.0;\n",19+i);
            else fprintf(output,"1e9;\n");
        }
    }
    const struct pl_shader_var *co=&r->variables[at++];
    if(co->var.dim_v!=4||co->var.dim_a!=(pc>2?8:1))return 0;
    int index=0;
    for(int s=0;s<(pc>2?8:1);s++) {
        fprintf(output,"%s",co->var.name);if(pc>2)fprintf(output,"[%d]",s);
        fprintf(output," = vec4(");
        if(s>=segments)fprintf(output,"0.0");
        else if(m[35+s*24]==0) {
            for(int k=0;k<3;k++) {
                if(k)fprintf(output,",");
                if(k<=m[36+s*24])fprintf(output,"float(m[%d])*coefficient_scale",38+s*24+k);
                else fprintf(output,"0.0");
            }
            fprintf(output,",0.0");
        } else {
            fprintf(output,"float(m[%d])*coefficient_scale,%d.0,0.0,float(m[%d])",37+s*24,index,36+s*24);
            index+=2*(int)m[36+s*24];
        }
        fprintf(output,");\n");
    }
    if(has_mmr) {
        const struct pl_shader_var *mm=&r->variables[at++];
        if(mm->var.dim_v!=4||mm->var.dim_a!=packed)return 0;
        index=0;
        for(int s=0;s<segments;s++)if(m[35+s*24]) {
            for(int order=0;order<m[36+s*24];order++)for(int group=0;group<2;group++) {
                fprintf(output,"%s",mm->var.name);
                if(packed>1)fprintf(output,"[%d]",index++);
                fprintf(output," = vec4(");
                for(int k=0;k<4;k++) {
                    if(k)fprintf(output,",");
                    if(group==0&&k==3)fprintf(output,"0.0");
                    else fprintf(output,"float(m[%d])*coefficient_scale",38+s*24+order*7+(group?3+k:k));
                }
                fprintf(output,");\n");
            }
        }
    }
    for(int bound=0;bound<2;bound++) {
        const struct pl_shader_var *b=&r->variables[at++];
        if(b->var.dim_v!=1||b->var.dim_a!=1)return 0;
        fprintf(output,"%s=float(m[%d])/1024.0;\n",b->var.name,bound?18+pc-1:18);
    }
    fprintf(output,"}\n");return at==expected;
}
static int emit_uniform_variables(FILE *output,const int64_t metadata[3][419],const struct pl_shader_res *r,int c)
{
    const int64_t *m=metadata[c];int pc=(int)m[17],has_mmr=0,packed=0;
    for(int s=0;s<pc-1;s++)if(m[35+s*24]) {
        has_mmr=1;packed+=2*(int)m[36+s*24];
    }
    if(r->num_variables!=3+(pc>2?1:0)+(has_mmr?1:0))return 0;
    fprintf(output,"// YB_FP_TOPOLOGY %d %d",c,pc);
    for(int s=0;s<8;s++)fprintf(output," %" PRId64 " %" PRId64,
        s<pc-1?m[35+s*24]:0,s<pc-1?m[36+s*24]:0);
    fprintf(output,"\n");
    int at=0;
    for(int role=0;role<5;role++) {
        const char *names[]={"pivots","coeffs","mmr","lo","hi"};
        if((role==0&&pc==2)||(role==2&&!has_mmr))continue;
        const struct pl_shader_var *v=&r->variables[at++];
        int dim=(role==1||role==2)?4:1;
        int array=role==0?7:role==1?(pc>2?8:1):role==2?packed:1;
        if(v->var.type!=PL_VAR_FLOAT||v->var.dim_m!=1||v->var.dim_v!=dim||v->var.dim_a!=array)return 0;
        fprintf(output,"uniform %s yb_fp_c%d_%s",dim==1?"float":"vec4",c,names[role]);
        if(array>1)fprintf(output,"[%d]",array);
        fprintf(output,";\n#define %s yb_fp_c%d_%s\n",v->var.name,c,names[role]);
    }
    return at==r->num_variables;
}
int yb_libplacebo_reshape_fragment(const int64_t metadata[3][419],char **text,size_t *bytes)
{
    if(!metadata||!text||!bytes||*text)return 2;
    char *buffer=NULL;size_t length=0;
    FILE *output=open_memstream(&buffer,&length);
    if(!output)return 3;
    int runtime=0,uniforms=1,native_output=1,status=0;
    /* Validate cross-component pivot counts before indexing companion blocks. */
    for(int c=0;c<3;c++)if(metadata[c][17]<2||metadata[c][17]>9){ status=2; goto done; }
    fprintf(output,"// Actual libplacebo BL reshaper; domain-preserving diagnostic adapter.\n");
    fprintf(output,"// Upstream float segment selection retained; %s output bounds.\n",
           native_output?"explicit native-range control":"upstream pivot");
    if(uniforms)fprintf(output,"// YB_FP_OUTPUT_RANGE_NATIVE %d\n",native_output);
    for(int c=0;c<3;c++) {
        struct pl_dovi_metadata d={0};
        if(!convert(metadata,c,&d)){ status=2; goto done; }
        struct pl_shader_params p={.id=(uint8_t)(c+1),.glsl={.version=430}};
        pl_shader sh=pl_shader_alloc(NULL,&p);
        if(!sh){ status=3; goto done; }
        pl_shader_dovi_reshape(sh,&d);
        const struct pl_shader_res *r=pl_shader_finalize(sh);
        if(!r||r->input!=PL_SHADER_SIG_COLOR||r->output!=PL_SHADER_SIG_COLOR||
           r->num_descriptors||r->num_constants||r->num_vertex_attribs||
           !(uniforms?emit_uniform_variables(output,metadata,r,c):runtime?emit_runtime_variables(output,metadata,r,c):emit_variables(output,r))) {
            pl_shader_free(&sh);{ status=3; goto done; }
        }
        /* Consume all names/data before freeing the owning shader object. */
        fprintf(output,"%s\nfloat yb_libplacebo_component_%d(vec3 s) { ",r->glsl,c);
        if(runtime||uniforms) {
            fprintf(output,"if (m[1]!=int64_t(%d) || m[4]!=int64_t(10) || m[5]<int64_t(1) || m[5]>int64_t(32) || m[17]!=int64_t(%" PRId64 ")",c,metadata[c][17]);
            for(int s=0;s<metadata[c][17]-1;s++)
                fprintf(output," || m[%d]!=int64_t(%" PRId64 ") || m[%d]!=int64_t(%" PRId64 ")",
                       35+s*24,metadata[c][35+s*24],36+s*24,metadata[c][36+s*24]);
            fprintf(output,") { atomicOr(frame_error,4u); return 0.0; }\n");
            if(runtime)fprintf(output,"yb_libplacebo_init_%d(); ",c);
        }
        fprintf(output,"return %s(vec4(s,1.0))[%d]; }\n",r->name,c);
        pl_shader_free(&sh);
    }
    if(uniforms)fprintf(output,"uniform vec3 yb_fp_input_lo;\nuniform vec3 yb_fp_input_hi;\n");
    fprintf(output,"float yb_libplacebo_reshape(uvec3 native_codes, int component) {\n");
    if(uniforms)fprintf(output,"vec3 s=clamp(vec3(native_codes),yb_fp_input_lo,yb_fp_input_hi)/1024.0;\n");
    else if(runtime)fprintf(output,"vec3 s=clamp(vec3(native_codes),vec3(float(m[11]),float(m[13]),float(m[15])),vec3(float(m[12]),float(m[14]),float(m[16])))/1024.0;\n");
    else fprintf(output,"vec3 s=clamp(vec3(native_codes),vec3(%" PRId64 ".0,%" PRId64 ".0,%" PRId64 ".0),vec3(%" PRId64 ".0,%" PRId64 ".0,%" PRId64 ".0))/1024.0;\n",
           metadata[0][11],metadata[0][13],metadata[0][15],metadata[0][12],metadata[0][14],metadata[0][16]);
    fprintf(output,"return component==0 ? yb_libplacebo_component_0(s) : component==1 ? yb_libplacebo_component_1(s) : yb_libplacebo_component_2(s);\n}\n");
done:
    if(ferror(output))status=4;
    if(fclose(output))status=4;
    if(status||length>1048576U){free(buffer);return status?status:4;}
    *text=buffer;*bytes=length;return 0;
}

