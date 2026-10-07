QSV base-layer renderer: mapped-frame display ownership candidate

Apply after native_qsv_bl_gbm_display_owner_candidate to the experimental Kodi
tree. This patch changes only QSV mapped-buffer display lookup and the GLES
renderer consumers. It does not change Dolby reconstruction or FFmpeg decode.

Observed on Petunia: BL hevc_qsv and EL QSV both returned a paired frame, but
Kodi selected the generic renderer and reported unsupported format vaapi.
No output frame was captured. The working Kodi binary/settings were restored.

The existing renderer adapter already recognizes CQsvMappedBuffer. Its QSV
checks used m_pWinSystem->GetVADisplay(), which performs a fresh GBM proxy lookup,
rather than the display retained by the mapped frame's device owner. This is
a source-supported candidate cause, not yet a hardware-proven diagnosis.

Display() retrieves the VAAPI display from the frame's retained hardware
context and returns it only after existing Valid() checks pass. GetMapped()
continues to require the exact decoder device context, direct mapping, P010,
Dolby metadata, a valid generation, and a non-quarantined buffer. The mapped
AVFrame retains the device/display owner. No CPU download or pixel changes.

The factory, configuration, reconfiguration, texture import, and native
reconstruction now consistently use that validated owned display. EGL still
uses the registered window proxy. Normal VAAPI buffers are unchanged.

Measured follow-up on Petunia: bounded build and library checks passed;
binary a9c537064d3aacde4267a09ae4ea19ad836f5105d0aed6e8a2ec94f268b08894.
Renderer selection advanced beyond the previous unsupported-format error.
BL and EL decoded/mapped over 1,000 paired frames, including after seeking.
However native reconstruction rejected the base frame with
undeclared-base-chroma-location, followed by qsv-base-native-required. The
user observed frozen video. Exact-frame capture timed out; test FAILED.
Decoder progress is NOT proof of displayed playback or output accuracy.
Working binary 19379 and original mount stack/settings/runtime/idle state
were restored. No OOM, swap, accuracy equality, or performance claim.
Further automatic iterations stopped pending reassessment of metadata
propagation from the software metadata parser into QSV returned frames.
