/* YBLOD 0.4.0: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10plus_analysis.c) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * The GLES pass is not ported (the Vulkan engine measures: shaders/pack.comp STATS); the analysis
 * context keeps only what the scene functions use, which YBLOD creates and names the picture of
 * (yblod_hdr10plus.c). Otherwise unchanged.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "cb1_hdr10plus_analysis.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

struct cb1_hdr10plus_scene {
    struct dvbridge_identity last;
    unsigned y99_nits;
    double y100_sum;
    uint64_t pictures;
};

/* YBLOD: the GLES context's fields left out (the pass isn't ported). */
struct cb1_hdr10plus_analysis {
    struct dvbridge_identity identity;
    struct cb1_hdr10plus_scene scene, pending_scene;
};

/* YBLOD: in place of cb1_hdr10plus_analysis_create, and of the identity
 * cb1_hdr10plus_analysis_submit records for the picture measured. */
struct cb1_hdr10plus_analysis *cb1_hdr10plus_analysis_create_scene(void)
{
    return calloc(1,sizeof(struct cb1_hdr10plus_analysis));
}

void cb1_hdr10plus_analysis_identify(struct cb1_hdr10plus_analysis *ctx,struct dvbridge_identity id)
{
    ctx->identity=id;
}

void cb1_hdr10plus_analysis_destroy(struct cb1_hdr10plus_analysis **ctx)
{
    if(!ctx || !*ctx)return;
    free(*ctx);*ctx=NULL;
}

void cb1_hdr10plus_analysis_clear_scene(struct cb1_hdr10plus_analysis *ctx)
{
    if(ctx)ctx->scene=(struct cb1_hdr10plus_scene){0};
}

static unsigned percentile_bin(const uint32_t histogram[256],uint64_t count,unsigned rank)
{
    const uint64_t need=(count*rank+9999)/10000;
    uint64_t seen=0;
    for(unsigned bin=0;bin<256;bin++){
        seen+=histogram[bin];
        if(seen>=need)return bin;
    }
    return 0;
}

static void scene_update(struct cb1_hdr10plus_scene *scene,
    struct cb1_hdr10plus_statistics *s,struct dvbridge_identity id,bool scene_refresh)
{
    if(!s->luminance_valid)return;
    const struct dvbridge_identity last=scene->last;
    if(!dvbridge_identity_equal(&last,&id)){
        /* A missing picture may have carried the scene cut. */
        if(scene_refresh || id.stream!=last.stream || id.revision!=last.revision ||
           id.picture<=last.picture || id.picture-last.picture>1)
            *scene=(struct cb1_hdr10plus_scene){0};
        if(s->y99_nits>scene->y99_nits)scene->y99_nits=s->y99_nits;
        scene->y100_sum+=s->y100_percent;
        scene->pictures++;
        scene->last=id;
    }
    s->y99_nits=scene->y99_nits;
    s->y100_percent=scene->y100_sum/scene->pictures;
}

void cb1_hdr10plus_analysis_stage_scene(struct cb1_hdr10plus_analysis *ctx,
    struct cb1_hdr10plus_statistics *s,bool scene_refresh)
{
    ctx->pending_scene=(struct cb1_hdr10plus_scene){0};
    if(!s->luminance_valid)return;
    ctx->pending_scene=ctx->scene;
    scene_update(&ctx->pending_scene,s,ctx->identity,scene_refresh);
}

void cb1_hdr10plus_analysis_commit_scene(struct cb1_hdr10plus_analysis *ctx)
{
    ctx->scene=ctx->pending_scene;
}

bool cb1_hdr10plus_describe(AVDynamicHDRPlus *out,const struct cb1_hdr10plus_statistics *s,unsigned target)
{
    return cb1_hdr10plus_describe_for_version(out,s,target,1);
}

bool cb1_hdr10plus_describe_for_version(AVDynamicHDRPlus *out,
    const struct cb1_hdr10plus_statistics *s,unsigned target,unsigned version)
{
    if(!out || !s || version>1 || !s->count || s->count>UINT32_MAX || !target || target>992 || target%32 ||
       !isfinite(s->average_maxrgb) || s->average_maxrgb<0 || s->average_maxrgb>10000)return false;
    uint64_t count=0;for(unsigned i=0;i<256;i++)count+=s->histogram[i];
    if(count!=s->count)return false;
    if(version==1 && s->luminance_valid &&
       (s->y99_nits>4080 || !isfinite(s->y100_percent) ||
        s->y100_percent<0 || s->y100_percent>100))return false;
    AVDynamicHDRPlus m={.itu_t_t35_country_code=0xb5,.application_version=version,.num_windows=1,
        .targeted_system_display_maximum_luminance={(int)target,1}};
    AVHDRPlusColorTransformParams *p=&m.params[0];
    p->window_upper_left_corner_x=p->window_upper_left_corner_y=(AVRational){0,1};
    p->window_lower_right_corner_x=p->window_lower_right_corner_y=(AVRational){1,1};
    for(unsigned i=0;i<3;i++){
        if(!isfinite(s->maxscl[i]) || s->maxscl[i]<0 || s->maxscl[i]>10000)return false;
        p->maxscl[i]=(AVRational){(int)lround(s->maxscl[i]*10),100000};
    }
    p->average_maxrgb=(AVRational){(int)lround(s->average_maxrgb*10),100000};
    if(p->average_maxrgb.num>p->maxscl[0].num && p->average_maxrgb.num>p->maxscl[1].num &&
       p->average_maxrgb.num>p->maxscl[2].num)return false;
    p->fraction_bright_pixels=(AVRational){0,1};
    static const uint8_t percent[]={1,5,10,25,50,75,90,95,99};
    static const unsigned rank[]={100,500,1000,2500,5000,7500,9000,9500,9998};
    p->num_distribution_maxrgb_percentiles=9;
    for(unsigned i=0;i<9;i++){
        unsigned value;
        if(version==1 && i==1)value=s->luminance_valid?s->y99_nits*10:0;
        else if(version==1 && i==2)value=s->luminance_valid?(unsigned)lround(s->y100_percent):255;
        else value=160*percentile_bin(s->histogram,s->count,rank[i]);
        p->distribution_maxrgb[i]=(AVHDRPlusPercentile){.percentage=percent[i],.percentile={(int)value,100000}};
    }
    *out=m;return true;
}
