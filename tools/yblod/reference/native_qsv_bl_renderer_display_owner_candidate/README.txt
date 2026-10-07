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

Status: source candidate; bounded incremental build started. No successful
playback, accuracy equality, or performance improvement claimed yet.
