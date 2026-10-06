Experimental Kodi BL-QSV GBM registered-display-owner fix
=======================================================

Status: source-only correction reviewed for ownership. No compilation or
corrected playback result is claimed by this package. Default BL-QSV OFF is
unchanged. The next corrected playback is a stop-and-reevaluate boundary if it
fails; this package does not authorize another build, test or retry.

Observed failure
----------------
The first combined BL+EL QSV Kodi ON capture selected the Intel Quick Sync HEVC
codec but produced no frame before the capture failed. Its log did not reach the
BL-QSV configured-async or successfully mapped-picture markers. Rollback passed.
This is distinct from the separately passing target raw FFmpeg picture proof.

Source cause
------------
The original OpenDVQsvDevice dynamically cast the Kodi window to
VAAPI::IVaapiWinSystem. The actual GBM window does not implement that interface;
GBM creates and registers a separate CVaapiProxy instead. The cast therefore
rejects this configuration before acquiring the VA context or deriving QSV.
This deterministic source defect matches the observed pre-configuration failure
boundary; the corrected build still needs actual playback evidence.

The patch reads the existing public VAAPI::CDecoder::m_pWinSystem only to guard
against absent registration before CVAAPIContext::EnsureContext dereferences it.
The acquired context's nonnull display is authoritative. It does not request an
independent display, change driver/device selection, add an API or bypass any
hardware-frame, pixel-format, crop, metadata or mapping check.

Relevant existing source
------------------------
xbmc/windowing/gbm/OptionalsReg.cpp: CVaapiProxy implements IVaapiWinSystem;
VAAPIRegister delegates to CDecoder::Register.
xbmc/windowing/gbm/WinSystemGbmGLESContext.cpp: constructs the proxy from the
actual render-node FD, configures EGL and registers VAAPI when supported.
xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.h: CDecoder's public section contains
m_pWinSystem, before protected; no access change is needed.
xbmc/cores/VideoPlayer/DVDCodecs/Video/VAAPI.cpp: EnsureContext/CreateContext uses
that registered proxy. Register itself already uses a nullable decoder owner.

Artifact identity
-----------------
Apply qsv-gbm-registered-display-owner.patch to the DVDVideoCodecFFmpeg.cpp from
native_qsv_bl_el_kodi_build_candidate (the 0436 Kodi candidate):
baseline SHA256 be1387b8b9213bc8e35073c2ebae2bac04e785d488716f34b654d2aa85d53f2d
corrected SHA256 8edd86f3ade2a1ebc4d21faf5fa03103ce38c9c5e2abd6d5811f4eb9e7db44ac
patch SHA256 8f96d986104d0af245f641a5727954118552a42ff81ce16ac8f901d7544e7e95

The patch touches only OpenDVQsvDevice. Separately proposed presentation timing
diagnostics are not included. OWNERSHIP_REVIEW.txt documents the unchanged
single-reference transfer/release paths. This package contains source and safe
failure analysis only, not media, captured frames, raw private logs or binaries.
