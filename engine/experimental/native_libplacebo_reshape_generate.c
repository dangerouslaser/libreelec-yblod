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
static int64_t metadata[COMPONENTS][WORDS];

static int read_metadata(const char *path)
{
    FILE *f=fopen(path,"rb");
    if(!f)return 0;
    for(int c=0;c<COMPONENTS;c++)for(int i=0;i<WORDS;i++) {
        unsigned char b[8];uint64_t u=0;
        if(fread(b,1,8,f)!=8){fclose(f);return 0;}
        for(int j=0;j<8;j++)u|=(uint64_t)b[j]<<(8*j);
        metadata[c][i]=u<=INT64_MAX ? (int64_t)u : -1-(int64_t)(UINT64_MAX-u);
    }
    int good=fgetc(f)==EOF&&!ferror(f);
    return fclose(f)==0&&good;
}
static int convert(int c,struct pl_dovi_metadata *d)
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
static int emit_float(float f)
{
    if(!isfinite(f))return 0;
    char text[64];int n=snprintf(text,sizeof(text),"%.9g",(double)f);
    if(n<0||(size_t)n>=sizeof(text))return 0;
    fputs(text,stdout);
    if(!strchr(text,'.')&&!strchr(text,'e')&&!strchr(text,'E'))fputs(".0",stdout);
    return 1;
}
static int emit_variables(const struct pl_shader_res *r)
{
    for(int i=0;i<r->num_variables;i++) {
        const struct pl_shader_var *v=&r->variables[i];
        if(v->var.type!=PL_VAR_FLOAT||v->var.dim_m!=1||
           v->var.dim_v<1||v->var.dim_v>4||v->var.dim_a<1||v->var.dim_a>48||!v->data)return 0;
        const char *type=v->var.dim_v==1?"float":v->var.dim_v==2?"vec2":v->var.dim_v==3?"vec3":"vec4";
        printf("const %s %s",type,v->var.name);
        if(v->var.dim_a>1)printf("[%d]",v->var.dim_a);
        printf(" = ");
        if(v->var.dim_a>1)printf("%s[%d](",type,v->var.dim_a);
        const float *data=v->data;
        for(int a=0;a<v->var.dim_a;a++) {
            if(a)printf(",");
            if(v->var.dim_v>1)printf("%s(",type);
            for(int k=0;k<v->var.dim_v;k++) {
                if(k)printf(",");
                if(!emit_float(data[a*v->var.dim_v+k]))return 0;
            }
            if(v->var.dim_v>1)printf(")");
        }
        if(v->var.dim_a>1)printf(")");
        printf(";\n");
    }
    return 1;
}
/* Runtime numerical metadata variant: generated function text is untouched.
 * Mutable globals are private to each shader invocation, not shared state.
 * Topology remains specialized as upstream generation specializes topology. */
static int emit_runtime_variables(const struct pl_shader_res *r,int c)
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
        printf("%s %s",v->var.dim_v==1?"float":"vec4",v->var.name);
        if(v->var.dim_a>1)printf("[%d]",v->var.dim_a);
        printf(";\n");
    }
    printf("void yb_libplacebo_init_%d() {\nfloat coefficient_scale=exp2(-float(m[5]));\n",c);
    int at=0;
    if(pc>2) {
        const struct pl_shader_var *p=&r->variables[at++];
        if(p->var.dim_v!=1||p->var.dim_a!=7)return 0;
        for(int i=0;i<7;i++) {
            printf("%s[%d] = ",p->var.name,i);
            if(i<pc-2)printf("float(m[%d])/1024.0;\n",19+i);
            else printf("1e9;\n");
        }
    }
    const struct pl_shader_var *co=&r->variables[at++];
    if(co->var.dim_v!=4||co->var.dim_a!=(pc>2?8:1))return 0;
    int index=0;
    for(int s=0;s<(pc>2?8:1);s++) {
        printf("%s",co->var.name);if(pc>2)printf("[%d]",s);
        printf(" = vec4(");
        if(s>=segments)printf("0.0");
        else if(m[35+s*24]==0) {
            for(int k=0;k<3;k++) {
                if(k)printf(",");
                if(k<=m[36+s*24])printf("float(m[%d])*coefficient_scale",38+s*24+k);
                else printf("0.0");
            }
            printf(",0.0");
        } else {
            printf("float(m[%d])*coefficient_scale,%d.0,0.0,float(m[%d])",37+s*24,index,36+s*24);
            index+=2*(int)m[36+s*24];
        }
        printf(");\n");
    }
    if(has_mmr) {
        const struct pl_shader_var *mm=&r->variables[at++];
        if(mm->var.dim_v!=4||mm->var.dim_a!=packed)return 0;
        index=0;
        for(int s=0;s<segments;s++)if(m[35+s*24]) {
            for(int order=0;order<m[36+s*24];order++)for(int group=0;group<2;group++) {
                printf("%s",mm->var.name);
                if(packed>1)printf("[%d]",index++);
                printf(" = vec4(");
                for(int k=0;k<4;k++) {
                    if(k)printf(",");
                    if(group==0&&k==3)printf("0.0");
                    else printf("float(m[%d])*coefficient_scale",38+s*24+order*7+(group?3+k:k));
                }
                printf(");\n");
            }
        }
    }
    for(int bound=0;bound<2;bound++) {
        const struct pl_shader_var *b=&r->variables[at++];
        if(b->var.dim_v!=1||b->var.dim_a!=1)return 0;
        printf("%s=float(m[%d])/1024.0;\n",b->var.name,bound?18+pc-1:18);
    }
    printf("}\n");return at==expected;
}
int main(int argc,char **argv)
{
    int runtime=argc==3&&strcmp(argv[1],"--runtime")==0;
    if((argc!=2&&!runtime)||!read_metadata(argv[runtime?2:1])) {
        fprintf(stderr,"usage: %s [--runtime] metadata-3x419-i64le.bin\n",argv[0]);return 2;
    }
    /* Validate cross-component pivot counts before indexing companion blocks. */
    for(int c=0;c<3;c++)if(metadata[c][17]<2||metadata[c][17]>9)return 2;
    printf("// Actual libplacebo BL reshaper; domain-preserving diagnostic adapter.\n");
    printf("// Upstream float segment selection and output-pivot clamp retained.\n");
    for(int c=0;c<3;c++) {
        struct pl_dovi_metadata d={0};
        if(!convert(c,&d))return 2;
        struct pl_shader_params p={.id=(uint8_t)(c+1),.glsl={.version=430}};
        pl_shader sh=pl_shader_alloc(NULL,&p);
        if(!sh)return 3;
        pl_shader_dovi_reshape(sh,&d);
        const struct pl_shader_res *r=pl_shader_finalize(sh);
        if(!r||r->input!=PL_SHADER_SIG_COLOR||r->output!=PL_SHADER_SIG_COLOR||
           r->num_descriptors||r->num_constants||r->num_vertex_attribs||
           !(runtime?emit_runtime_variables(r,c):emit_variables(r))) {
            pl_shader_free(&sh);return 3;
        }
        /* Consume all names/data before freeing the owning shader object. */
        printf("%s\nfloat yb_libplacebo_component_%d(vec3 s) { ",r->glsl,c);
        if(runtime) {
            printf("if (m[1]!=int64_t(%d) || m[4]!=int64_t(10) || m[5]<int64_t(1) || m[5]>int64_t(32) || m[17]!=int64_t(%" PRId64 ")",c,metadata[c][17]);
            for(int s=0;s<metadata[c][17]-1;s++)
                printf(" || m[%d]!=int64_t(%" PRId64 ") || m[%d]!=int64_t(%" PRId64 ")",
                       35+s*24,metadata[c][35+s*24],36+s*24,metadata[c][36+s*24]);
            printf(") { atomicOr(frame_error,4u); return 0.0; }\n");
            printf("yb_libplacebo_init_%d(); ",c);
        }
        printf("return %s(vec4(s,1.0))[%d]; }\n",r->name,c);
        pl_shader_free(&sh);
    }
    printf("float yb_libplacebo_reshape(uvec3 native_codes, int component) {\n");
    if(runtime)printf("vec3 s=clamp(vec3(native_codes),vec3(float(m[11]),float(m[13]),float(m[15])),vec3(float(m[12]),float(m[14]),float(m[16])))/1024.0;\n");
    else printf("vec3 s=clamp(vec3(native_codes),vec3(%" PRId64 ".0,%" PRId64 ".0,%" PRId64 ".0),vec3(%" PRId64 ".0,%" PRId64 ".0,%" PRId64 ".0))/1024.0;\n",
           metadata[0][11],metadata[0][13],metadata[0][15],metadata[0][12],metadata[0][14],metadata[0][16]);
    printf("return component==0 ? yb_libplacebo_component_0(s) : component==1 ? yb_libplacebo_component_1(s) : yb_libplacebo_component_2(s);\n}\n");
    return fflush(stdout)==0&&!ferror(stdout)?0:4;
}
