/* YBLOD 0.4.0: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10plus_analysis.c) at commit 9eb35aeb1146e9a6c3652b7a43225511887cdc17 (upstream/main, 2026-11-07).
 * Only cb1_hdr10plus_describe and _for_version (unchanged); the GLES pass is not ported.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "cb1_hdr10plus_analysis.h"
#include <math.h>
#include <string.h>

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
        unsigned value=version==1 && i==2?255:0;
        if(version==0 || (i!=1 && i!=2)){
            uint64_t need=(s->count*rank[i]+9999)/10000,seen=0;
            for(unsigned bin=0;bin<256;bin++){
                seen+=s->histogram[bin];if(seen>=need){value=bin*160;break;}
            }
        }
        p->distribution_maxrgb[i]=(AVHDRPlusPercentile){.percentage=percent[i],.percentile={(int)value,100000}};
    }
    *out=m;return true;
}
