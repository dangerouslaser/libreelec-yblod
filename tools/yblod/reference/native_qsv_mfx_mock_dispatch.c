/* CPU-only versioned dispatcher fixture. No GPU or media processing. */
#include <vpl/mfxvideo.h>
mfxStatus MFX_CDECL MFXVideoDECODE_Init(mfxSession s,mfxVideoParam *p)
{ (void)s; p->mfx.FrameInfo.Width=999; return MFX_WRN_IN_EXECUTION; }
mfxStatus MFX_CDECL MFXVideoDECODE_QueryIOSurf(mfxSession s,mfxVideoParam *p,mfxFrameAllocRequest *r)
{ (void)s;(void)p;r->NumFrameMin=3;r->NumFrameSuggested=7;return MFX_ERR_NONE; }
