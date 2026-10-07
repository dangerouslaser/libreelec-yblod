/* Synthetic P010 upload/readback only; no decoder or film data. */
#include <vpl/mfxdispatcher.h>
#include <vpl/mfxvideo.h>
#include <va/va_drm.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static unsigned code(unsigned p,unsigned x,unsigned y)
{
    return p ? (x&1U ? 600U+(x/2)*3U+y*3U : 200U+(x/2)*7U+y*5U)
             : 64U+(x*17U+y*11U)%800U;
}
int main(int argc,char **argv)
{
    unsigned requested_mode=MFX_SCALING_MODE_INTEL_GEN_VEBOX;
    unsigned requested_interpolation=MFX_INTERPOLATION_NEAREST_NEIGHBOR;
    if(argc==2 && !strcmp(argv[1],"vebox-bilinear"))requested_interpolation=MFX_INTERPOLATION_BILINEAR;
    else if(argc==2 && !strcmp(argv[1],"compute-nearest"))requested_mode=MFX_SCALING_MODE_INTEL_GEN_COMPUTE;
    else if(argc!=1)return 2;
    int fd=open("/dev/dri/renderD128",O_RDWR|O_CLOEXEC),major=0,minor=0;
    if(fd<0)return 1;
    VADisplay display=vaGetDisplayDRM(fd);
    if(!display || vaInitialize(display,&major,&minor)!=VA_STATUS_SUCCESS){close(fd);return 1;}
    mfxLoader loader=MFXLoad();mfxSession session=NULL;
    mfxStatus status=MFX_ERR_UNKNOWN;
    if(!loader)goto done;
    mfxConfig config=MFXCreateConfig(loader);
    mfxVariant value={0};value.Type=MFX_VARIANT_TYPE_U32;value.Data.U32=MFX_IMPL_TYPE_HARDWARE;
    status=MFXSetConfigFilterProperty(config,(const mfxU8*)"mfxImplDescription.Impl",value);
    if(status<0)goto done;
    value.Data.U32=MFX_ACCEL_MODE_VIA_VAAPI;
    status=MFXSetConfigFilterProperty(config,(const mfxU8*)"mfxImplDescription.AccelerationMode",value);
    if(status<0)goto done;
    status=MFXCreateSession(loader,0,&session);if(status<0)goto done;
    status=MFXVideoCORE_SetHandle(session,MFX_HANDLE_VA_DISPLAY,display);if(status<0)goto done;
    for(unsigned mode=1;mode<2;mode++){
        mfxExtVPPScaling scaling={0};
        scaling.Header.BufferId=MFX_EXTBUFF_VPP_SCALING;scaling.Header.BufferSz=sizeof(scaling);
        scaling.ScalingMode=(mfxU16)requested_mode;
        scaling.InterpolationMethod=(mfxU16)requested_interpolation;
        mfxExtBuffer *extensions[]={&scaling.Header};
        mfxVideoParam input={0},output={0};
        input.IOPattern=MFX_IOPATTERN_IN_SYSTEM_MEMORY|MFX_IOPATTERN_OUT_SYSTEM_MEMORY;
        input.AsyncDepth=1;input.NumExtParam=1;input.ExtParam=extensions;
        input.vpp.In.FourCC=MFX_FOURCC_P010;input.vpp.In.Width=input.vpp.In.Height=32;
        input.vpp.In.CropW=input.vpp.In.CropH=32;
        input.vpp.In.ChromaFormat=MFX_CHROMAFORMAT_YUV420;
        input.vpp.In.BitDepthLuma=input.vpp.In.BitDepthChroma=10;input.vpp.In.Shift=1;
        input.vpp.In.PicStruct=MFX_PICSTRUCT_PROGRESSIVE;
        input.vpp.In.FrameRateExtN=24;input.vpp.In.FrameRateExtD=1;
        input.vpp.Out=input.vpp.In;
        input.vpp.Out.Width=input.vpp.Out.Height=input.vpp.Out.CropW=input.vpp.Out.CropH=64;
        mfxExtVPPScaling returned=scaling;mfxExtBuffer *out_extensions[]={&returned.Header};
        output.NumExtParam=1;output.ExtParam=out_extensions;
        status=MFXVideoVPP_Query(session,&input,&output);
        printf("{\"query_only\":true,\"requested_scaling_mode\":%u,\"requested_interpolation\":%u,\"status\":%d,\"returned_scaling_mode\":%u,\"returned_interpolation\":%u}\n",
            scaling.ScalingMode,scaling.InterpolationMethod,status,returned.ScalingMode,returned.InterpolationMethod);
        if(status!=MFX_ERR_NONE || returned.InterpolationMethod!=requested_interpolation || returned.ScalingMode!=requested_mode){status=MFX_ERR_UNSUPPORTED;break;}
        status=MFXVideoVPP_Init(session,&output);
        printf("{\"stage\":\"init\",\"status\":%d}\n",status);
        if(status!=MFX_ERR_NONE)break;
        mfxExtVPPScaling observed={0};observed.Header=scaling.Header;
        mfxExtBuffer *get_extensions[]={&observed.Header};mfxVideoParam active={0};
        active.NumExtParam=1;active.ExtParam=get_extensions;
        status=MFXVideoVPP_GetVideoParam(session,&active);
        if(status!=0 || observed.InterpolationMethod!=requested_interpolation || observed.ScalingMode!=requested_mode){status=MFX_ERR_UNSUPPORTED;MFXVideoVPP_Close(session);break;}
        mfxU16 *src=calloc(32U*32U*3U/2U,sizeof(*src));
        mfxU16 *dst=calloc(64U*64U*3U/2U,sizeof(*dst));
        if(!src || !dst){free(src);free(dst);status=MFX_ERR_MEMORY_ALLOC;MFXVideoVPP_Close(session);break;}
        for(unsigned p=0;p<2;p++)for(unsigned y=0;y<(p?16U:32U);y++)for(unsigned x=0;x<32;x++)
            src[(p?1024U:0U)+y*32+x]=(mfxU16)(code(p,x,y)<<6);
        mfxFrameSurface1 in={0},out={0};in.Info=active.vpp.In;out.Info=active.vpp.Out;
        in.Data.Y16=src;in.Data.U16=src+1024;in.Data.V16=src+1025;in.Data.Pitch=64;
        out.Data.Y16=dst;out.Data.U16=dst+4096;out.Data.V16=dst+4097;out.Data.Pitch=128;
        in.Data.TimeStamp=0;mfxSyncPoint sync=NULL;
        status=MFXVideoVPP_RunFrameVPPAsync(session,&in,&out,NULL,&sync);
        if(status==MFX_ERR_MORE_DATA)status=MFXVideoVPP_RunFrameVPPAsync(session,NULL,&out,NULL,&sync);
        printf("{\"stage\":\"submit\",\"status\":%d,\"sync_point\":%s}\n",status,sync?"true":"false");
        if(status==0 && sync)status=MFXVideoCORE_SyncOperation(session,sync,5000);
        else if(status==0)status=MFX_ERR_UNKNOWN;
        if(status==0){
            unsigned mismatch[2]={0},fractional=0;
            for(unsigned p=0;p<2;p++)for(unsigned y=0;y<(p?32U:64U);y++)for(unsigned x=0;x<64;x++){
                unsigned word=dst[(p?4096U:0U)+y*64+x];
                unsigned ix=p?(x/4)*2+(x&1U):x/2;
                mismatch[p]+=word!=(code(p,ix,y/2)<<6);fractional+=(word&63U)!=0;
            }
            printf("{\"synthetic_pixels_tested\":true,\"luma_words\":4096,\"chroma_words\":2048,\"luma_mismatches\":%u,\"chroma_mismatches\":%u,\"fractional_words\":%u,\"scaling_mode\":%u,\"interpolation\":%u,\"probe_cpu_upload_readback\":true,\"production_zero_copy_tested\":false}\n",
                mismatch[0],mismatch[1],fractional,observed.ScalingMode,observed.InterpolationMethod);
            printf("{\"synthetic_luma_prefix\":[");
            for(unsigned i=0;i<12;i++)printf("%s%u",i?",":"",dst[i]);
            printf("]}\n");
            if(requested_interpolation==1 && (mismatch[0] || mismatch[1] || fractional))status=MFX_ERR_UNKNOWN;
        }
        MFXVideoVPP_Close(session);free(src);free(dst);
    }
done:
    if(session)MFXClose(session);
    if(loader)MFXUnload(loader);
    vaTerminate(display);close(fd);
    return status<0?1:0;
}
