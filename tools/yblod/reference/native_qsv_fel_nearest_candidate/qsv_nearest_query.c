/* Capability query only: no decoder, film data or GPU pixel processing. */
#include <vpl/mfxdispatcher.h>
#include <vpl/mfxvideo.h>
#include <va/va_drm.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
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
    for(unsigned mode=0;mode<2;mode++){
        mfxExtVPPScaling scaling={0};
        scaling.Header.BufferId=MFX_EXTBUFF_VPP_SCALING;scaling.Header.BufferSz=sizeof(scaling);
        scaling.ScalingMode=mode?MFX_SCALING_MODE_INTEL_GEN_VEBOX:MFX_SCALING_MODE_DEFAULT;
        scaling.InterpolationMethod=MFX_INTERPOLATION_NEAREST_NEIGHBOR;
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
        printf("{\"query_only\":true,\"requested_scaling_mode\":%u,\"requested_interpolation\":1,\"status\":%d,\"returned_scaling_mode\":%u,\"returned_interpolation\":%u}\n",
            scaling.ScalingMode,status,returned.ScalingMode,returned.InterpolationMethod);
    }
done:
    if(session)MFXClose(session);
    if(loader)MFXUnload(loader);
    vaTerminate(display);close(fd);
    return status<0?1:0;
}
