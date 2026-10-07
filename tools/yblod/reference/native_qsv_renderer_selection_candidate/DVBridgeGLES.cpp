/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "DVBridgeGLES.h"

extern "C"
{
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
}

#include "cores/VideoPlayer/DVDCodecs/Video/DVOutputSettings.h"
#include "DVBridgeShaders.h"
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
#include "DVBridgeNativeShaders.h"
extern "C"
{
#include "native_playback_context.h"
}
#endif
#include "cores/VideoPlayer/DVDCodecs/Video/DVPlaybackInfo.h"
#include "cores/VideoPlayer/DVDCodecs/Video/DVStreamTelemetry.h"
#include "utils/log.h"
extern "C"
{
#include <libavutil/dovi_meta.h>
#include "dvbridge_placebo.h"
#include "dvbridge_fel.h"
}

#include <EGL/egl.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <GLES3/gl3.h>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>

namespace
{
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
// A failed in-flight context may still own decoded storage. Disable new native
// attempts for this process; retain its allocation until process/display
// teardown rather than recycling uncertain resources or repeatedly allocating.
std::atomic<bool> nativeCleanupRetained{false};
bool NativeTimingRequested()
{
  const char* value = std::getenv("DVBRIDGE_NATIVE_DIAGNOSTICS");
  return value && std::strcmp(value, "1") == 0;
}
bool NativeElapsedNs(const timespec& begin, const timespec& end, uint64_t& ns)
{
  if (begin.tv_sec < 0 || end.tv_sec < begin.tv_sec || begin.tv_nsec < 0 ||
      begin.tv_nsec >= 1000000000 || end.tv_nsec < 0 || end.tv_nsec >= 1000000000)
    return false;
  uint64_t seconds = static_cast<uint64_t>(end.tv_sec - begin.tv_sec);
  int64_t fraction = static_cast<int64_t>(end.tv_nsec) - static_cast<int64_t>(begin.tv_nsec);
  if (fraction < 0)
  {
    if (!seconds)
      return false;
    --seconds;
    fraction += 1000000000;
  }
  if (seconds > (UINT64_MAX - static_cast<uint64_t>(fraction)) / 1000000000)
    return false;
  ns = seconds * 1000000000 + static_cast<uint64_t>(fraction);
  return true;
}
void LogNativeTimings(yb_native_playback_context* context)
{
  if (!NativeTimingRequested())
    return;
  yb_native_playback_diagnostics stats{};
  stats.version = 1;
  if (yb_native_playback_diagnostics_get(context, &stats) != YB_NATIVE_PLAYBACK_OK ||
      !stats.enabled || !stats.valid || !stats.completed_frames || stats.completed_frames % 120 != 0)
    return;
  const auto perFrameMs = [&](unsigned stage)
  {
    return static_cast<double>(stats.stages[stage].total_wall_ns) /
        static_cast<double>(stats.completed_frames) / 1000000.0;
  };
  // Cumulative host-wall stage totals per successfully released frame.
  // Not GPU kernel time, unique displayed frames, or a complete render budget.
  CLog::Log(LOGINFO,
      "DVBridge native timing: released_frames={} valid={} wall_ms_per_released_frame "
      "scaler_submit={:.3f} va_wait={:.3f} imports={:.3f} prep_submit={:.3f} prep_wait={:.3f} "
      "composer_submit={:.3f} composer_wait={:.3f} ycc_submit={:.3f} ycc_wait={:.3f} "
      "bridge={:.3f} consumer_release={:.3f}",
      stats.completed_frames, stats.valid,
      perFrameMs(YB_NATIVE_TIMING_SCALER_SUBMIT), perFrameMs(YB_NATIVE_TIMING_VA_WAIT),
      perFrameMs(YB_NATIVE_TIMING_IMPORT), perFrameMs(YB_NATIVE_TIMING_PREPARATION_SUBMIT),
      perFrameMs(YB_NATIVE_TIMING_PREPARATION_WAIT), perFrameMs(YB_NATIVE_TIMING_COMPOSER_SUBMIT),
      perFrameMs(YB_NATIVE_TIMING_COMPOSER_WAIT), perFrameMs(YB_NATIVE_TIMING_YCC_SUBMIT),
      perFrameMs(YB_NATIVE_TIMING_YCC_WAIT), perFrameMs(YB_NATIVE_TIMING_BRIDGE),
      perFrameMs(YB_NATIVE_TIMING_RELEASE));
  yb_gpu_fp32_stats composer{};
  yb_gpu_nlq_lut_stats lut{};
  lut.version = 1;
  yb_native_playback_batch_stats batch{};
  yb_gpu_fp32_instruction_stats instruction{};
  instruction.version = 1;
  const bool optimizationStatsValid =
      yb_native_playback_get_batch_stats(context, &batch) == YB_NATIVE_PLAYBACK_OK &&
      yb_native_playback_get_instruction_stats(context, &instruction, sizeof(instruction)) == YB_NATIVE_PLAYBACK_OK;
  if (yb_native_playback_fp32_get_stats(context, &composer) == YB_NATIVE_PLAYBACK_OK &&
      yb_native_playback_nlq_lut_get_stats(context, &lut, sizeof(lut)) == YB_NATIVE_PLAYBACK_OK)
  {
    // Accepted submits are not unique displayed frames. Route selection is
    // the latest accepted submit, not merely an environment-variable request.
    CLog::Log(LOGINFO,
        "DVBridge native composer: released_frames={} fp32_selected={} "
        "accepted_fp32={} accepted_integer={} cache_hits={} cache_misses={} "
        "shader_compile_failed={} generate_failed={} nlq_lut_enabled={} accepted_lut={} "
        "nlq_shader_compiles={} nlq_builds={} nlq_uploads={} nlq_cache_hits={} "
        "optimization_stats_valid={} batched_planes_selected={} immutable_instructions_selected={} "
        "batched_plane_imports={} batched_plane_releases={} immutable_accepted_frames={} "
        "immutable_metadata_uploads={} immutable_range_bindings={} immutable_dispatches={}",
        stats.completed_frames, yb_native_playback_fp32_selected(context),
        composer.accepted_fp32, composer.accepted_integer, composer.cache_hits,
        composer.cache_misses, composer.shader_compile_failed, composer.generate_failed,
        lut.enabled, lut.accepted_frames, lut.shader_compiles, lut.builds, lut.uploads, lut.cache_hits,
        optimizationStatsValid ? 1 : 0, batch.selected, instruction.enabled,
        batch.imports, batch.releases, instruction.accepted_frames,
        instruction.metadata_uploads, instruction.range_bindings, instruction.dispatches);
  }
}
#endif
void BackendLog(void*, pl_log_level level, const char* message)
{
  // Error-only callback: no debug shader dumps or GPU timing/readback queries.
  // Shared across renderer recreation so repeated setup errors stay bounded.
  static std::mutex mutex;
  static DVBRIDGE::DiagnosticFailures failures;
  std::lock_guard<std::mutex> lock(mutex);
  if (failures.Record(DVBRIDGE::DiagnosticNowMs(), "graphics", int(level)))
    CLog::Log(LOGERROR, "DVBridge graphics: level={} detail={}", int(level),
        std::string_view(message ? message : "unavailable").substr(0, 768));
}
}

namespace
{
unsigned PQCode(float nits)
{
  const double y = std::pow(std::clamp(static_cast<double>(nits) / 10000.0, 0.0, 1.0), 2610.0 / 16384);
  const double e = std::pow((3424.0 / 4096 + 2413.0 / 128 * y) / (1 + 2392.0 / 128 * y), 2523.0 / 32);
  return static_cast<unsigned>(std::lround(e * 4095));
}

void SetIptOffset(dvbridge_renderer* renderer, dvbridge_gl_packer* packer)
{
  static constexpr float zero[3] = {0.0f, 0.0f, 0.0f};
  const float* offset = DVBRIDGE::playbackMatchHardware.load() ? DVBRIDGE::kHardwareIptOffset : zero;
  dvbridge_renderer_set_ipt_offset(renderer, offset);
  dvbridge_gl_packer_set_ipt_offset(packer, offset);
}
} // namespace

bool CDVBridgeGLES::Failure(const char* stage)
{
  if (DVBRIDGE::DiagnosticsEnabled() && m_failures.Record(DVBRIDGE::DiagnosticNowMs(), stage))
    CLog::Log(LOGERROR, "DVBridge renderer: stage={} failures={}", stage, m_failures.Count());
  return false;
}

void CDVBridgeGLES::Summary(const char* event)
{
  if (!DVBRIDGE::DiagnosticsEnabled() || m_lastReported == m_prepares)
    return;
  CLog::Log(LOGINFO,
      "DVBridge renderer {}: prepared={} direct={} composed={} presented={} presentation_failures={} stage_failures={} native_planar={} el_qsv_prepared={} el_qsv_native_used={}",
      event, m_prepares, m_directFrames, m_prepares - m_directFrames,
      m_presentations, m_failedPresentations, m_failures.Count(), m_nativePlanarFrames,
      m_elQsvPreparedFrames, m_elQsvNativeFrames);
  m_lastReported = m_prepares;
}

CDVBridgeGLES::~CDVBridgeGLES()
{
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
  if (NativeTimingRequested())
    CLog::Log(LOGINFO, "DVBridge native shutdown: renderer destroy begin native_present={} cleanup_retained={}",
        m_native != nullptr, nativeCleanupRetained.load());
  if (!ReleaseNative())
  {
    if (NativeTimingRequested())
      CLog::Log(LOGWARNING, "DVBridge native shutdown: renderer destroy retained; no uncertain resources freed");
    return;
  }
  if (NativeTimingRequested())
    CLog::Log(LOGINFO, "DVBridge native shutdown: renderer native release complete");
#endif
  Summary("closed");
  CDVPlaybackInfo::presented.store(0);
  glDeleteFramebuffers(1, &m_framebuffer);
  dvbridge_gl_packer_destroy(m_packer);
  dvbridge_renderer_destroy(m_renderer);
  dvbridge_vpp_destroy(&m_vpp);
  if (m_gl)
    pl_tex_destroy(m_gl->gpu, &m_scanout);
  pl_opengl_destroy(&m_gl);
  pl_log_destroy(&m_log);
}

bool CDVBridgeGLES::Initialize(bool allowSoftware, bool hdr10)
{
  if (m_gl)
    return m_renderer && m_packer;
  m_hdr10 = hdr10;
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
  const char* native = std::getenv("DVBRIDGE_NATIVE_RECONSTRUCTION");
  m_nativeRequested = !hdr10 && native && std::strcmp(native, "1") == 0;
#endif
  const char* capture = std::getenv("DVBRIDGE_CAPTURE_PAIRS");
  m_capturePairs = capture && std::strcmp(capture, "1") == 0;
  const char* outputCapture = std::getenv("DVBRIDGE_CAPTURE_OUTPUTS");
  m_captureOutputs = outputCapture && std::strcmp(outputCapture, "1") == 0;
  pl_opengl_params params{};
  params.get_proc_addr = reinterpret_cast<pl_voidfunc_t (*)(const char*)>(eglGetProcAddress);
  params.egl_display = eglGetCurrentDisplay();
  params.egl_context = eglGetCurrentContext();
  params.allow_software = allowSoftware;
  if (params.egl_context == EGL_NO_CONTEXT)
    return Failure("no-egl-context");
  if (DVBRIDGE::DiagnosticsEnabled() && !m_log)
  {
    pl_log_params logging{};
    logging.log_cb = BackendLog;
    logging.log_level = PL_LOG_ERR;
    m_log = pl_log_create(PL_API_VER, &logging);
  }
  m_gl = pl_opengl_create(m_log, &params);
  if (!m_gl)
    return Failure("opengl-create");
  // GUI alpha blending takes place in the 32F PQ target, before transport packing.
  if (!pl_opengl_has_ext(m_gl, "GL_EXT_float_blend") ||
      !pl_opengl_has_ext(m_gl, "GL_OES_texture_float_linear"))
    return Failure("float-blend-or-linear-unavailable");
  m_renderer = dvbridge_renderer_create(m_gl->gpu);
  pl_opengl_wrap_params output{};
  output.width = 3840;
  output.height = 2160;
  GLint draw, read, red, green, blue, samples, encoding;
  glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
  glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &read);
  glBindFramebuffer(GL_FRAMEBUFFER, 0);
  glGetIntegerv(GL_RED_BITS, &red);
  glGetIntegerv(GL_GREEN_BITS, &green);
  glGetIntegerv(GL_BLUE_BITS, &blue);
  glGetIntegerv(GL_SAMPLES, &samples);
  glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_BACK,
      GL_FRAMEBUFFER_ATTACHMENT_COLOR_ENCODING, &encoding);
  if (glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE &&
      ((hdr10 && red >= 10 && green >= 10 && blue >= 10) ||
       (!hdr10 && red == 8 && green == 8 && blue == 8)) &&
      samples <= 1 && encoding == GL_LINEAR)
    m_scanout = pl_opengl_wrap(m_gl->gpu, &output);
  m_outputBits = std::min(red, std::min(green, blue));
  glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw);
  glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
  m_packer = dvbridge_gl_packer_create(DVBRIDGE_VERTEX, DVBRIDGE_FRAGMENT);
  if (DVBRIDGE::DiagnosticsEnabled())
    CLog::Log(LOGINFO, "DVBridge renderer init: rgb={}/{}/{} samples={} linear={} direct_target={} renderer={} packer={}",
        red, green, blue, samples, encoding == GL_LINEAR, m_scanout != nullptr,
        m_renderer != nullptr, m_packer != nullptr);
  return m_renderer && m_packer && (!hdr10 || m_scanout);
}

void CDVBridgeGLES::Reset()
{
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
  if (!ReleaseNative())
    return;
  m_nativeFailed = false;
  m_nativeFailClosed = false;
#endif
  Summary("reset");
  m_nativePrepared = false;
  m_elDecoderQsv = m_elQsvNativeUsed = false;
  m_elQsvMapSequence = 0;
  m_nativePresented = 0;
  m_nativeColourCalls = m_nativeColourWallNs = m_nativeColourCpuNs = 0;
  m_nativeColourTimingValid = true;
  m_firstFrame = true;
  CDVPlaybackInfo::presented.store(0);
  m_pendingInfo = 0;
  m_prepared = m_packed = false;
  m_direct = false;
  dvbridge_renderer_reset(m_renderer);
  m_conversionUsable = true;
  m_lastConversionPath = -1;
  m_captureWaiting = false;
  m_outputCaptureMetadata.clear();
  m_outputCaptureWaiting = false;
  // Playback ended: free the media-engine surfaces and the decoder's VA device reference.
  dvbridge_vpp_release(m_vpp);
  m_vppFailed = false;
  m_vppLogged = false;
}

void CDVBridgeGLES::CapturePair(const pl_frame& frame, const CDVMetadataBuffer& metadata,
                               double pts, double elPts, dvbridge_geometry geometry)
{
  const uint64_t now = DVBRIDGE::DiagnosticNowMs();
  if (!m_captureWaiting && now - m_lastCapturePoll < 250)
    return;
  m_lastCapturePoll = now;
  constexpr const char* request = "/storage/dvbridge-captures/request";
  struct stat status{};
  if (lstat(request, &status) != 0 || !S_ISREG(status.st_mode))
  {
    m_captureWaiting = false;
    return;
  }
  m_captureWaiting = true;
  // An empty request captures the next frame; otherwise require its source PTS in microseconds.
  double requestedPts = pts;
  if (status.st_size)
  {
    FILE* file = std::fopen(request, "r");
    if (!file)
      return;
    const bool parsed = std::fscanf(file, "%lf", &requestedPts) == 1;
    std::fclose(file);
    if (!parsed || !std::isfinite(requestedPts) || requestedPts < 0)
      requestedPts = -1;
    if (pts < requestedPts - 1000.0)
      return;
  }
  char directory[] = "/storage/dvbridge-captures/pair-XXXXXX";
  if (!mkdtemp(directory))
    return;
  const std::string prefix = std::string(directory) + "/";
  if (std::rename(request, (prefix + "request").c_str()) != 0)
    return;
  m_captureWaiting = false;

  // A separate renderer keeps diagnostic candidates out of the presentation transaction.
  pl_tex target = nullptr;
  dvbridge_renderer* renderer = nullptr;
  auto write = [&](const char* name, const void* data, size_t size) {
    FILE* file = std::fopen((prefix + name).c_str(), "wb");
    if (!file)
      return false;
    const bool written = std::fwrite(data, 1, size, file) == size;
    return std::fclose(file) == 0 && written;
  };
  const bool success = [&]() {
    if (requestedPts < 0 || std::fabs(pts - requestedPts) > 1000.0)
      return false;
    struct statvfs space{};
    if (statvfs(directory, &space) != 0 ||
        static_cast<uint64_t>(space.f_bavail) * space.f_frsize < 256ULL * 1024 * 1024)
      return false;
    constexpr size_t bytes = 3840ULL * 2160 * 4;
    std::unique_ptr<void, decltype(&std::free)> pixels(std::malloc(bytes), &std::free);
    if (!pixels)
      return false;
    pl_tex_params params{};
    params.w = 3840;
    params.h = 2160;
    params.format = pl_find_named_fmt(m_gl->gpu, "rgba8");
    params.renderable = params.host_readable = true;
    if (!params.format || params.format->texel_size != 4)
      return false;
    target = pl_tex_create(m_gl->gpu, &params);
    renderer = dvbridge_renderer_create(m_gl->gpu);
    if (!target || !renderer)
      return false;
    static constexpr float zero[3] = {};
    const float* offset = DVBRIDGE::playbackMatchHardware.load() ? DVBRIDGE::kHardwareIptOffset : zero;
    dvbridge_renderer_set_ipt_offset(renderer, offset);
    unsigned margins[4]{};
    unsigned packets = 0;
    for (int direct = 0; direct != 2; ++direct)
    {
      dvbridge_renderer_reset(renderer);
      dvbridge_renderer_set_direct_conversion(renderer, direct != 0);
      if (!dvbridge_render_packed(renderer, &frame, metadata.Data(), metadata.Size(),
                                   pts, elPts, geometry, target, true) ||
          dvbridge_renderer_used_direct_conversion(renderer) != (direct != 0))
        return false;
      const auto* candidate = dvbridge_render_candidate(renderer);
      if (!dvbridge_active_area(candidate, margins) || !dvbridge_packets(candidate, &packets))
        return false;
      pl_tex_transfer_params transfer{};
      transfer.tex = target;
      transfer.ptr = pixels.get();
      if (!pl_tex_download(m_gl->gpu, &transfer) ||
          !write(direct ? "direct.rgba" : "release.rgba", pixels.get(), bytes))
        return false;
    }
    if (!write("metadata.bin", metadata.Data(), metadata.Size()))
      return false;
    char info[1024];
    const int size = std::snprintf(info, sizeof(info),
        "{\"width\":3840,\"height\":2160,\"format\":\"RGBA8 DV tunnel\","
        "\"pts\":%.17g,\"el_pts\":%.17g,\"requested_pts\":%.17g,\"qsv_mode\":%d,"
        "\"ipt_offset\":[%.9g,%.9g,%.9g],\"margins_lrtb\":[%u,%u,%u,%u],"
        "\"metadata_packets\":%u,\"same_decoded_input\":true}\n",
        pts, elPts, requestedPts, DVBRIDGE::playbackQsvMode.load(), static_cast<double>(offset[0]),
        static_cast<double>(offset[1]), static_cast<double>(offset[2]),
        margins[0], margins[1], margins[2], margins[3], packets);
    return size > 0 && static_cast<size_t>(size) < sizeof(info) && write("pair.json", info, size);
  }();
  dvbridge_renderer_destroy(renderer);
  pl_tex_destroy(m_gl->gpu, &target);
  CLog::Log(success ? LOGINFO : LOGERROR,
            "DVBridge capture pair: success={} directory={} pts={} requested_pts={}",
            success, directory, pts, requestedPts);
}

bool CDVBridgeGLES::Prepare(const Layer& base, const Layer* enhancement,
                          const CDVMetadataBuffer& metadata, dvbridge_geometry geometry, bool allowPacked,
                          pl_tex reconstructed,
                          const dvbridge_native_colour_association* nativeAssociation,
                          const dvbridge_native_planar* planar)
{
  if (!m_hardwarePreparing)
  {
    m_elDecoderQsv = m_elQsvNativeUsed = false;
    m_elQsvMapSequence = 0;
  }
  m_prepared = m_packed = false;
  m_nativePrepared = false;
  m_nativePlanarPrepared = false;
  m_nativeColourNoReimport = false;
  m_direct = false;
  if (!m_renderer)
    return Failure("renderer-unavailable");
  if (!metadata.Data())
    return Failure("metadata-unavailable");
  SetIptOffset(m_renderer, m_packer);
  const bool requestedConversion = DVBRIDGE::playbackDirectConversion.load();
  dvbridge_renderer_set_direct_conversion(m_renderer, !reconstructed && !planar && requestedConversion && m_conversionUsable);
  dvbridge_gl_frame bl{}, el{};
  if (nativeAssociation && ((!reconstructed && !planar) || enhancement ||
                           !dvbridge_native_colour_association_valid(nativeAssociation)))
    return Failure("native-colour-association");
  if (!nativeAssociation && !dvbridge_gl_frame_import(&bl, m_gl->gpu, base.layout, base.width, base.height, base.planes))
    return Failure("base-import");
  double elPts = nativeAssociation ? nativeAssociation->enhancement_presentation_pts :
                                    std::numeric_limits<double>::quiet_NaN();
  if (enhancement)
  {
    if (!dvbridge_gl_frame_import(&el, m_gl->gpu, enhancement->layout,
                                 enhancement->width, enhancement->height, enhancement->planes))
    {
      dvbridge_gl_frame_release(&bl);
      return Failure("enhancement-import");
    }
    bl.frame.enhancement_layer = &el.frame;
    elPts = enhancement->pts;
  }
  const char* nativePacked = std::getenv("DVBRIDGE_NATIVE_PACKED_OUTPUT");
  if ((reconstructed || planar) && nativeAssociation && nativePacked && std::strcmp(nativePacked, "1") == 0 &&
      !m_hdr10 && allowPacked && m_directUsable && m_scanout && !geometry.x && !geometry.y &&
      geometry.source_width == 3840 && geometry.source_height == 2160 &&
      geometry.width == 3840 && geometry.height == 2160)
  {
    m_direct = planar ? dvbridge_render_native_planar_packed(
        m_renderer, nativeAssociation, planar, metadata.Data(), metadata.Size(),
        geometry, m_scanout, true) : dvbridge_render_native_reconstructed_packed(
        m_renderer, nativeAssociation, reconstructed, metadata.Data(), metadata.Size(),
        geometry, m_scanout, true);
    if (!m_direct)
    {
      CLog::Log(LOGWARNING, "DVBridge native packed output failed; using composition");
      m_directUsable = false;
      dvbridge_renderer_reset(m_renderer);
    }
  }
  // The fast path produces the exact transport bytes directly. GUI/subtitle
  // frames and non-fullscreen geometry retain the original 32F composition.
  if (!reconstructed && !planar && !m_hdr10 && allowPacked && m_directUsable && m_scanout && !geometry.x && !geometry.y &&
      geometry.width == 3840 && geometry.height == 2160)
  {
    // Finish readback before rendering the real output; capture never replaces scanout.
    if (m_capturePairs && enhancement && bl.frame.rotation == PL_ROTATION_0 &&
        geometry.source_width == 3840 && geometry.source_height == 2160 &&
        std::isfinite(base.pts) && std::isfinite(elPts))
      CapturePair(bl.frame, metadata, base.pts, elPts, geometry);
    m_direct = dvbridge_render_packed(m_renderer, &bl.frame, metadata.Data(), metadata.Size(),
                                     base.pts, elPts, geometry, m_scanout, true);
    if (!m_direct && requestedConversion && m_conversionUsable)
    {
      // Retry this very frame using the release path, keeping its metadata and
      // enhancement layer paired. Do not retry the experiment until next play.
      CLog::Log(LOGWARNING, "DVBridge direct conversion failed; retrying release renderer");
      m_conversionUsable = false;
      dvbridge_renderer_reset(m_renderer);
      dvbridge_renderer_set_direct_conversion(m_renderer, false);
      m_direct = dvbridge_render_packed(m_renderer, &bl.frame, metadata.Data(), metadata.Size(),
                                       base.pts, elPts, geometry, m_scanout, true);
    }
    if (!m_direct)
    {
      Failure("direct-path-unavailable-using-composition");
      m_directUsable = false;
      dvbridge_renderer_reset(m_renderer);
    }
  }
  const auto renderRGB = m_hdr10 ? dvbridge_render_hdr10_rgb : dvbridge_render_rgb;
  m_prepared = m_direct || (planar
      ? (!m_hdr10 && dvbridge_render_native_planar_rgb(m_renderer, nativeAssociation, planar,
                                                     metadata.Data(), metadata.Size(), geometry)) : (reconstructed
      ? (!m_hdr10 && (nativeAssociation
          ? dvbridge_render_native_reconstructed_rgb(m_renderer, nativeAssociation, reconstructed,
                                                    metadata.Data(), metadata.Size(), geometry)
          : dvbridge_render_reconstructed_rgb(m_renderer, &bl.frame, reconstructed,
                                             metadata.Data(), metadata.Size(), base.pts, elPts, geometry)))
      : (m_direct || renderRGB(m_renderer, &bl.frame, metadata.Data(), metadata.Size(),
                              base.pts, elPts, geometry))));
  m_pendingInfo = 0;
  if (m_prepared)
  {
    // The renderer has validated all metadata offsets and extension bounds.
    const auto* parsed = reinterpret_cast<const AVDOVIMetadata*>(metadata.Data());
    // An enhancement surface can also belong to MEL. Report FEL only when
    // the same mapping used by the renderer actually reconstructs residuals.
    dvbridge_color color{};
    const bool fel = (enhancement || nativeAssociation) &&
                     dvbridge_map_color(&color, metadata.Data(), metadata.Size(), true) &&
                     color.dovi.nlq_active;
    DVBRIDGE::StreamTelemetry::Metadata(parsed, fel, m_outputBits);
    m_pendingInfo = (m_hdr10 ? CDVPlaybackInfo::HDR10 : CDVPlaybackInfo::HDMI) |
                   (fel ? CDVPlaybackInfo::FEL : 0u);
    for (int i = 0; i < parsed->num_ext_blocks; ++i)
    {
      const auto level = av_dovi_get_ext(parsed, i)->level;
      if (level == 3 || level == 8 || level == 9 || level == 10 || level == 11 || level == 254)
        m_pendingInfo |= CDVPlaybackInfo::CM4;
    }
  }
  dvbridge_gl_frame_release(&el);
  dvbridge_gl_frame_release(&bl);
  if (!m_prepared)
    return Failure("render-prepare");
  m_nativePrepared = reconstructed != nullptr || planar != nullptr;
  m_nativePlanarPrepared = planar != nullptr;
  m_nativeColourNoReimport = nativeAssociation != nullptr;
  const int conversionPath = dvbridge_renderer_used_direct_conversion(m_renderer) ? 1 : 0;
  if (conversionPath != m_lastConversionPath)
  {
    CLog::Log(LOGINFO, "DVBridge conversion: requested={} active={} packed={} source={}x{} rotation={}",
              requestedConversion, conversionPath ? "direct-lms" : "release-rgb", m_direct,
              base.width, base.height, base.layout == DVBRIDGE_Y416_BASE_ROT180 ? 180 : 0);
    m_lastConversionPath = conversionPath;
  }
  if (DVBRIDGE::DiagnosticsEnabled())
  {
    ++m_prepares;
    m_directFrames += m_direct;
    m_nativePlanarFrames += planar != nullptr;
    m_elQsvPreparedFrames += m_elDecoderQsv;
    if (m_firstFrame)
    {
      m_firstFrame = false;
      m_lastSummary = DVBRIDGE::DiagnosticNowMs();
      CLog::Log(LOGINFO, "DVBridge first frame: source={}x{} output={}x{} offset={},{} enhancement={} fel={} cm4={} direct={}",
          base.width, base.height, geometry.width, geometry.height, geometry.x, geometry.y,
          enhancement != nullptr, bool(m_pendingInfo & CDVPlaybackInfo::FEL),
          bool(m_pendingInfo & CDVPlaybackInfo::CM4), m_direct);
    }
  }
  if (m_captureOutputs && m_prepared && !m_hdr10)
  {
    m_outputCapturePts = base.pts;
    m_outputCaptureElPts = elPts;
    const auto* bytes = static_cast<const unsigned char*>(metadata.Data());
    m_outputCaptureMetadata.assign(bytes, bytes + metadata.Size());
  }
  return m_prepared;
}

unsigned int CDVBridgeGLES::GetPQTexture() const
{
  const auto texture = m_prepared ? dvbridge_render_texture(m_renderer) : nullptr;
  return texture ? pl_opengl_unwrap(m_gl->gpu, texture, nullptr, nullptr, nullptr) : 0;
}

#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
bool CDVBridgeGLES::ReleaseNative()
{
  if (!m_native)
    return true;
  const int status = yb_native_playback_destroy(&m_native);
  if (NativeTimingRequested())
    CLog::Log(LOGINFO, "DVBridge native shutdown: native destroy status={} handle_retained={}",
        status, m_native != nullptr);
  if (status == YB_NATIVE_PLAYBACK_OK)
    return true;
  yb_native_playback_quarantine_retained(m_native);
  // Never free an uncertain in-flight context or its retained decoder refs.
  m_nativeFailed = true;
  nativeCleanupRetained.store(true);
  CLog::Log(LOGERROR, "DVBridge native reconstruction: cleanup retained status={}", status);
  return false;
}

bool CDVBridgeGLES::PrepareNative(const Layer& base, const AVFrame* enhancement,
                                const CDVMetadataBuffer& metadata, dvbridge_geometry geometry,
                                bool allowPacked)
{
  if (!base.decodedFrame || !enhancement || !base.vaDisplay ||
      base.layout != DVBRIDGE_P010 || base.decodedSourcePts == AV_NOPTS_VALUE ||
      enhancement->pts == AV_NOPTS_VALUE || !metadata.Data() ||
      base.width <= 0 || base.height <= 0 || enhancement->width <= 0 || enhancement->height <= 0)
    return false;
  bool nativeCompleted = false;
  auto fail = [&](const char* stage, int status)
  {
    m_nativeFailed = true;
    m_nativeFailClosed = m_nativeFailClosed || (nativeCompleted && m_nativePlanar);
    CLog::Log(LOGWARNING, "DVBridge native reconstruction: stage={} status={} fallback={}",
              stage, status, m_nativeFailClosed ? "none-fail-closed" : "release");
    return false;
  };
  yb_dovi_integer_instructions instructions{};
  const int metadataStatus = yb_dovi_to_integer_configs(metadata.Data(), metadata.Size(), &instructions);
  if (metadataStatus != YB_DOVI_ADAPTER_OK)
    return fail("metadata", metadataStatus);
  if (base.decodedFrame->chroma_location != AVCHROMA_LOC_LEFT &&
      base.decodedFrame->chroma_location != AVCHROMA_LOC_TOPLEFT)
    return fail("undeclared-base-chroma-location", YB_NATIVE_PLAYBACK_FALLBACK);
  // No implicit phase policy: this candidate selects cubic128 explicitly.
  // The VA scaler separately declares top-left EL input and left output.
  if (enhancement->chroma_location != AVCHROMA_LOC_TOPLEFT)
    return fail("undeclared-enhancement-chroma-location", YB_NATIVE_PLAYBACK_FALLBACK);
  if (!enhancement->hw_frames_ctx || !enhancement->hw_frames_ctx->data ||
      enhancement->hw_frames_ctx->size < sizeof(AVHWFramesContext))
    return fail("enhancement-hardware-reference", YB_NATIVE_PLAYBACK_FALLBACK);
  const auto* frames = reinterpret_cast<const AVHWFramesContext*>(enhancement->hw_frames_ctx->data);
  const auto* hardwareDevice = frames->device_ref && frames->device_ref->data &&
          frames->device_ref->size >= sizeof(AVHWDeviceContext)
      ? reinterpret_cast<const AVHWDeviceContext*>(frames->device_ref->data) : nullptr;
  if (enhancement->format != AV_PIX_FMT_VAAPI || !frames ||
      frames->format != AV_PIX_FMT_VAAPI || frames->sw_format != AV_PIX_FMT_P010 ||
      !hardwareDevice || hardwareDevice->type != AV_HWDEVICE_TYPE_VAAPI ||
      !hardwareDevice->hwctx)
    return fail("enhancement-device-format", YB_NATIVE_PLAYBACK_FALLBACK);
  const auto* device = static_cast<const AVVAAPIDeviceContext*>(hardwareDevice->hwctx);
  if (device->display != base.vaDisplay)
    return fail("enhancement-device-display", YB_NATIVE_PLAYBACK_FALLBACK);
  yb_native_playback_create_info info{};
  info.version = 2;
  info.egl_display = reinterpret_cast<uintptr_t>(eglGetCurrentDisplay());
  info.va_display = base.vaDisplay;
  info.enhancement_scaler = {
      static_cast<uint32_t>(enhancement->width), static_cast<uint32_t>(enhancement->height),
      static_cast<uint32_t>(base.width), static_cast<uint32_t>(base.height),
      YB_VPP_BILINEAR, 1, VA_SOURCE_RANGE_FULL,
      VA_CHROMA_SITING_VERTICAL_TOP | VA_CHROMA_SITING_HORIZONTAL_LEFT,
      VA_CHROMA_SITING_VERTICAL_CENTER | VA_CHROMA_SITING_HORIZONTAL_LEFT};
  info.base_chroma_location = base.decodedFrame->chroma_location == AVCHROMA_LOC_LEFT ? 0u : 1u;
  info.phase_filter = 2; // Explicit cubic128 experimental preparation contract.
  info.preparation = {YBLOD_NATIVE::preparation, sizeof(YBLOD_NATIVE::preparation)-1};
  info.composer = {YBLOD_NATIVE::composer, sizeof(YBLOD_NATIVE::composer)-1};
  info.ycc_expansion = {YBLOD_NATIVE::ycc, sizeof(YBLOD_NATIVE::ycc)-1};
  std::memcpy(info.guide_contract_id, "guide-quarter-round-each-pass-v1", 32);
  std::memcpy(info.phase_contract_id, "phase-cubic128-left-explicit-v1", 31);
  std::memcpy(info.enhancement_scale_contract_id, "va-bilinear-fast-top-left-v1", 28);
  if (!m_native)
  {
    m_nativeColourCalls = m_nativeColourWallNs = m_nativeColourCpuNs = 0;
    m_nativeColourTimingValid = true;
    const char* nlq = std::getenv("DVBRIDGE_NATIVE_NLQ_LUT");
    if (nlq && std::strcmp(nlq, "0") && std::strcmp(nlq, "1"))
      return fail("nlq_lut flag", YB_NATIVE_PLAYBACK_ARGUMENT);
    const bool nlqRequested = nlq && !std::strcmp(nlq, "1");
    const char* fp32 = std::getenv("DVBRIDGE_NATIVE_FP32");
    if (nlqRequested && (!fp32 || std::strcmp(fp32, "1")))
      return fail("nlq_lut requires fp32", YB_NATIVE_PLAYBACK_ARGUMENT);
    const char* planarFlag = std::getenv("DVBRIDGE_NATIVE_PLANAR_OUTPUT");
    if (planarFlag && std::strcmp(planarFlag, "0") && std::strcmp(planarFlag, "1"))
      return fail("planar output flag", YB_NATIVE_PLAYBACK_ARGUMENT);
    m_nativePlanar = planarFlag && !std::strcmp(planarFlag, "1");
    const char* noReimportFlag = std::getenv("DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT");
    if (m_nativePlanar && (!fp32 || std::strcmp(fp32, "1") ||
                          !noReimportFlag || std::strcmp(noReimportFlag, "1")))
      return fail("planar requires fp32 native colour admission", YB_NATIVE_PLAYBACK_ARGUMENT);
    const char* batchFlag = std::getenv("DVBRIDGE_NATIVE_BATCHED_PLANES");
    const char* instructionFlag = std::getenv("DVBRIDGE_NATIVE_IMMUTABLE_INSTRUCTIONS");
    if ((batchFlag && std::strcmp(batchFlag, "0") && std::strcmp(batchFlag, "1")) ||
        (instructionFlag && std::strcmp(instructionFlag, "0") && std::strcmp(instructionFlag, "1")))
      return fail("native optimization flag", YB_NATIVE_PLAYBACK_ARGUMENT);
    const bool batchRequested = batchFlag && !std::strcmp(batchFlag, "1");
    const bool instructionRequested = instructionFlag && !std::strcmp(instructionFlag, "1");
    if ((batchRequested && !m_nativePlanar) ||
        (instructionRequested && (!fp32 || std::strcmp(fp32, "1"))))
      return fail("native optimization requires matching route", YB_NATIVE_PLAYBACK_ARGUMENT);
    const yb_native_playback_options options{
        1, static_cast<uint32_t>(YB_NATIVE_PLAYBACK_FP32 |
            (nlqRequested ? YB_NATIVE_PLAYBACK_NLQ_LUT : 0) |
            (m_nativePlanar ? YB_NATIVE_PLAYBACK_PLANAR_OUTPUT : 0) |
            (batchRequested ? YB_NATIVE_PLAYBACK_BATCHED_PLANES : 0) |
            (instructionRequested ? YB_NATIVE_PLAYBACK_IMMUTABLE_INSTRUCTIONS : 0)), {0, 0}};
    const int status = (nlqRequested || m_nativePlanar || instructionRequested) ? yb_native_playback_create_ex(&info, &options, &m_native)
                                    : yb_native_playback_create(&info, &m_native);
    if (status != YB_NATIVE_PLAYBACK_OK)
      return fail("create", status);
    if (NativeTimingRequested() &&
        yb_native_playback_diagnostics_enable(m_native, 1) != YB_NATIVE_PLAYBACK_OK)
      CLog::Log(LOGWARNING, "DVBridge native timing: enable failed; playback unchanged");
  }
  yb_native_playback_frame request{};
  auto& association = request.association;
  association.version = 1;
  association.width = association.el_scaled_width = static_cast<uint32_t>(base.width);
  association.height = association.el_scaled_height = static_cast<uint32_t>(base.height);
  association.guide_width = association.width/2;
  association.guide_height = association.height/2;
  association.bl_pts = base.decodedSourcePts;
  association.el_pts = enhancement->pts;
  association.bl_timebase_num = association.el_timebase_num = base.decodedPacketTimeBase.num;
  association.bl_timebase_den = association.el_timebase_den = base.decodedPacketTimeBase.den;
  const uintptr_t instance = reinterpret_cast<uintptr_t>(this);
  if (++m_nativeSerial == 0)
    return fail("frame-counter-wrap", YB_NATIVE_PLAYBACK_ARGUMENT);
  std::memcpy(association.frame_id, &instance, sizeof(instance));
  std::memcpy(association.frame_id+8, &m_nativeSerial, sizeof(m_nativeSerial));
  std::memcpy(association.metadata_frame_id, association.frame_id, 32);
  std::memcpy(association.el_frame_id, association.frame_id, 32);
  std::memcpy(association.guide_frame_id, association.frame_id, 32);
  std::memcpy(association.preparation_id, info.guide_contract_id, 32);
  std::memcpy(association.guide_preparation_id, info.guide_contract_id, 32);
  std::memcpy(association.enhancement_scale_id, info.enhancement_scale_contract_id, 32);
  association.input_native_depth = 10;
  association.spatial_filter_flag = instructions.spatial_resampling_filter_flag;
  association.el_spatial_filter_flag = instructions.el_spatial_resampling_filter_flag;
  association.colour_route = YB_PLAYBACK_COLOUR_INHERITED;
  request.base_frame = base.decodedFrame;
  request.enhancement_frame = enhancement;
  request.base_surface = base.vaSurface;
  request.enhancement_surface = static_cast<unsigned>(reinterpret_cast<uintptr_t>(enhancement->data[3]));
  request.base_width = association.width;
  request.base_height = association.height;
  request.enhancement_width = static_cast<uint32_t>(enhancement->width);
  request.enhancement_height = static_cast<uint32_t>(enhancement->height);
  request.base_packet_timebase_num = request.enhancement_packet_timebase_num = base.decodedPacketTimeBase.num;
  request.base_packet_timebase_den = request.enhancement_packet_timebase_den = base.decodedPacketTimeBase.den;
  request.expanded_dovi_side_data = metadata.Data();
  request.expanded_dovi_side_data_bytes = metadata.Size();
  if (base.nativeRenderGuard)
  {
    request.base_storage = YB_NATIVE_BASE_KODI_SURFACE;
    request.kodi_base.version = 1;
    request.kodi_base.fourcc = base.nativeFourcc;
    request.kodi_base.allocation_width = base.nativeAllocationWidth;
    request.kodi_base.allocation_height = base.nativeAllocationHeight;
    request.kodi_base.va_display = base.vaDisplay;
    request.kodi_base.generation = base.nativeGeneration;
    request.kodi_base.owner_identity = base.nativeOwnerIdentity;
    request.kodi_base.render_guard = base.nativeRenderGuard;
    request.kodi_base.validate = base.nativeValidate;
    request.kodi_base.mark_quarantine = base.nativeQuarantine;
  }
  const int submitted = yb_native_playback_submit(m_native, &request, 1000000000);
  if (submitted != YB_NATIVE_PLAYBACK_OK)
    return fail("submit", submitted);
  yb_native_playback_output output{};
  yb_native_playback_planar_output planarOutput{};
  planarOutput.version = 1;
  const int finished = m_nativePlanar
      ? yb_native_playback_finish_planar(m_native, 1000000000, &planarOutput)
      : yb_native_playback_finish(m_native, 1000000000, &output);
  if (finished != YB_NATIVE_PLAYBACK_OK)
    return fail("finish", finished);
  // A completed native reconstruction must never be replaced by older math.
  nativeCompleted = true;
  if (m_nativePlanar)
  {
    if (planarOutput.version != 1 || planarOutput.output_depth != 12 || planarOutput.sampling_contract != 1)
      return fail("planar output contract", YB_NATIVE_PLAYBACK_ERROR);
    output.width = planarOutput.width;
    output.height = planarOutput.height;
    std::memcpy(output.frame_id, planarOutput.frame_id, 32);
  }
  if (std::memcmp(output.frame_id, association.frame_id, 32) ||
      output.width != association.width || output.height != association.height)
    return fail("output-association", YB_NATIVE_PLAYBACK_ERROR);
  pl_opengl_wrap_params wrap{};
  wrap.texture = output.texture;
  wrap.target = GL_TEXTURE_2D;
  wrap.iformat = GL_RGBA32F;
  wrap.width = base.width;
  wrap.height = base.height;
  timespec colourBegin{}, colourCpuBegin{};
  const bool colourTimingRequested = NativeTimingRequested();
  const bool colourTimingStarted = colourTimingRequested &&
      clock_gettime(CLOCK_MONOTONIC, &colourBegin) == 0 &&
      clock_gettime(CLOCK_THREAD_CPUTIME_ID, &colourCpuBegin) == 0;
  if (colourTimingRequested && !colourTimingStarted)
    m_nativeColourTimingValid = false;
  pl_tex reconstructed = m_nativePlanar ? nullptr : pl_opengl_wrap(m_gl->gpu, &wrap);
  dvbridge_native_planar planar{};
  bool planarReady = m_nativePlanar;
  if (m_nativePlanar)
  {
    planar.width = output.width;
    planar.height = output.height;
    planar.output_depth = planarOutput.output_depth;
    planar.sampling_contract = planarOutput.sampling_contract;
    for (unsigned i = 0; i < 3; ++i)
    {
      wrap.texture = planarOutput.textures[i];
      wrap.iformat = GL_R16UI;
      wrap.width = i ? base.width / 2 : base.width;
      wrap.height = i ? base.height / 2 : base.height;
      planar.textures[i] = pl_opengl_wrap(m_gl->gpu, &wrap);
      planarReady = planarReady && planar.textures[i];
    }
  }
  dvbridge_dmabuf imported{};
  bool prepared = false;
  const char* noReimport = std::getenv("DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT");
  const bool omitColourImports = noReimport && std::strcmp(noReimport, "1") == 0;
  dvbridge_native_colour_association proof{};
  proof.version = 1;
  proof.width = output.width;
  proof.height = output.height;
  proof.enhancement_width = static_cast<unsigned>(enhancement->width);
  proof.enhancement_height = static_cast<unsigned>(enhancement->height);
  proof.vaapi_p010_admitted = 1;
  proof.unrotated = 1;
  proof.reconstructed_depth = 12;
  proof.bl_pts = association.bl_pts;
  proof.el_pts = association.el_pts;
  proof.timebase_num = association.bl_timebase_num;
  proof.timebase_den = association.bl_timebase_den;
  std::memcpy(proof.expected_frame_id, association.frame_id, 32);
  std::memcpy(proof.reconstructed_frame_id, output.frame_id, 32);
  proof.presentation_pts = base.pts;
  proof.enhancement_presentation_pts = static_cast<double>(enhancement->pts);
  const auto materializeRGBA = [&]()
  {
    // The producer cannot reuse planes until all queued consumer reads finish.
    pl_gpu_flush(m_gl->gpu);
    for (auto& plane : planar.textures)
      pl_tex_destroy(m_gl->gpu, &plane);
    planarReady = false;
    yb_native_playback_output rgba{};
    int status = YB_NATIVE_PLAYBACK_PENDING;
    for (unsigned attempt = 0; attempt < 5 && status == YB_NATIVE_PLAYBACK_PENDING; ++attempt)
      status = yb_native_playback_materialize_rgba(m_native, 1000000000, &rgba);
    if (status != YB_NATIVE_PLAYBACK_OK)
    {
      // Timeout or uncertain transition retains the completed reconstruction.
      yb_native_playback_quarantine_retained(m_native);
      nativeCleanupRetained.store(true);
      return false;
    }
    if (std::memcmp(rgba.frame_id, association.frame_id, 32) ||
        rgba.width != association.width || rgba.height != association.height)
      return false;
    wrap.texture = rgba.texture;
    wrap.iformat = GL_RGBA32F;
    wrap.width = base.width;
    wrap.height = base.height;
    reconstructed = pl_opengl_wrap(m_gl->gpu, &wrap);
    if (reconstructed)
      CLog::Log(LOGWARNING, "DVBridge planar output: same-native RGBA materialized; no legacy reconstruction");
    return reconstructed != nullptr;
  };
  // Unsupported planar geometry uses the identical native RGBA expansion,
  // rather than risking a cropped native hook or changing composer pipelines.
  const bool planarGeometry = !m_hdr10 && !geometry.x && !geometry.y &&
      geometry.source_width == 3840 && geometry.source_height == 2160 &&
      geometry.width == 3840 && geometry.height == 2160;
  bool materialized = false;
  if (m_nativePlanar && (!planarReady || !planarGeometry))
  {
    materialized = true;
    materializeRGBA();
  }
  if ((reconstructed || planarReady) && omitColourImports)
  {
    prepared = Prepare(base, nullptr, metadata, geometry, allowPacked, reconstructed, &proof,
                       planarReady ? &planar : nullptr);
    if (!prepared && planarReady && !materialized)
    {
      dvbridge_renderer_retry_native_colour(m_renderer);
      if (materializeRGBA())
        prepared = Prepare(base, nullptr, metadata, geometry, allowPacked, reconstructed, &proof);
    }
  }
  else if (reconstructed && dvbridge_dmabuf_import(&imported, enhancement))
  {
    Layer originalEnhancement{};
    originalEnhancement.layout = imported.layout;
    originalEnhancement.width = enhancement->width;
    originalEnhancement.height = enhancement->height;
    originalEnhancement.pts = static_cast<double>(enhancement->pts);
    for (int p=0; p<3; ++p)
      originalEnhancement.planes[p] = imported.planes[p];
    prepared = Prepare(base, &originalEnhancement, metadata, geometry, false, reconstructed);
  }
  // Submit libplacebo's queued consumer commands before the context fences.
  pl_gpu_flush(m_gl->gpu);
  pl_tex_destroy(m_gl->gpu, &reconstructed);
  for (auto& plane : planar.textures)
    pl_tex_destroy(m_gl->gpu, &plane);
  dvbridge_dmabuf_release(&imported);
  if (colourTimingStarted)
  {
    timespec colourEnd{}, colourCpuEnd{};
    uint64_t wallNs = 0, cpuNs = 0;
    if (!prepared || clock_gettime(CLOCK_MONOTONIC, &colourEnd) != 0 ||
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &colourCpuEnd) != 0 ||
        !NativeElapsedNs(colourBegin, colourEnd, wallNs) ||
        !NativeElapsedNs(colourCpuBegin, colourCpuEnd, cpuNs) ||
        m_nativeColourCalls == UINT64_MAX ||
        wallNs > UINT64_MAX - m_nativeColourWallNs ||
        cpuNs > UINT64_MAX - m_nativeColourCpuNs)
      m_nativeColourTimingValid = false;
    else
    {
      ++m_nativeColourCalls;
      m_nativeColourWallNs += wallNs;
      m_nativeColourCpuNs += cpuNs;
    }
  }
  const int released = yb_native_playback_release(m_native, 1000000000);
  if (released != YB_NATIVE_PLAYBACK_OK)
    return fail("consumer-release", released);
  if (prepared && m_elDecoderQsv)
  {
    // The current tagged EL was supplied to this exact native request;
    // submit, finish, association, colour prepare and release all succeeded.
    m_elQsvNativeUsed = true;
    if (DVBRIDGE::DiagnosticsEnabled())
      ++m_elQsvNativeFrames;
  }
  LogNativeTimings(m_native);
  if (colourTimingRequested && m_nativeColourCalls && m_nativeColourCalls % 120 == 0)
    CLog::Log(LOGINFO,
        "DVBridge native colour handoff: calls={} valid={} imports={} wall_ms_per_call={:.3f} thread_cpu_ms_per_call={:.3f} scope=wrap-prepare-flush-destroy-excludes-native-release",
        m_nativeColourCalls, m_nativeColourTimingValid,
        omitColourImports ? "metadata-only" : "original-bl-el-reimport",
        static_cast<double>(m_nativeColourWallNs) / static_cast<double>(m_nativeColourCalls) / 1000000.0,
        static_cast<double>(m_nativeColourCpuNs) / static_cast<double>(m_nativeColourCalls) / 1000000.0);
  return prepared || fail("colour-only-render", YB_NATIVE_PLAYBACK_ERROR);
}
#endif

bool CDVBridgeGLES::PrepareHardware(const Layer& base, const AVFrame* enhancement,
                                  const CDVMetadataBuffer& metadata, dvbridge_geometry geometry, bool allowPacked)
{
  m_prepared = m_packed = false;
  m_nativePrepared = m_nativePlanarPrepared = false;
  m_elDecoderQsv = m_elQsvNativeUsed = false;
  m_elQsvMapSequence = 0;
  const int elRoute = enhancement ? dvbridge_fel_qsv_frame_route(enhancement, &m_elQsvMapSequence) : 0;
  const char* qsvFlag = std::getenv("DVBRIDGE_FEL_QSV");
  if (elRoute < 0 || (qsvFlag && std::strcmp(qsvFlag, "0") && std::strcmp(qsvFlag, "1")) ||
      (enhancement && qsvFlag && !std::strcmp(qsvFlag, "1") && elRoute != 1))
    return Failure("el-qsv-route-proof");
  m_elDecoderQsv = elRoute == 1;
  // Recursive colour-only Prepare calls inherit only this hardware frame's
  // proof. Standalone Prepare calls clear it; no prior-frame inference.
  struct ScopedHardwarePrepare
  {
    bool& active;
    ~ScopedHardwarePrepare() { active = false; }
  } guard{m_hardwarePreparing};
  m_hardwarePreparing = true;
  m_prepared = m_packed = false;
  m_nativePrepared = false;
  m_nativePlanarPrepared = false;
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
  if (m_nativeFailClosed)
    return false;
  if (m_nativeRequested && !m_nativeFailed && !nativeCleanupRetained.load() &&
      PrepareNative(base, enhancement, metadata, geometry, allowPacked))
    return true;
  if (base.nativeOnly)
  {
    return Failure("qsv-base-native-required");
  }
  if (m_nativeFailed && !nativeCleanupRetained.load())
    ReleaseNative();
  if (m_nativeFailClosed)
    return false;
  if (base.nativeRenderGuard && (!base.nativeValidate ||
      !base.nativeValidate(base.nativeOwnerIdentity, base.vaDisplay, base.vaSurface,
                           base.nativeGeneration, base.nativeAllocationWidth,
                           base.nativeAllocationHeight)))
    return false;
#endif
  if (base.nativeOnly)
    return Failure("qsv-base-native-unavailable");
  // Quick Sync scaling on the Intel media engine (see dvbridge_vpp.c):
  //  mode 1: the FEL enhancement layer is upscaled there (default);
  //  mode 2: base layer colour is upsampled there too. Both layers then come back rotated by 180
  //          degrees (that makes the driver filter colour properly) and the renderer turns the
  //          composed picture back.
  // If anything fails, this playback continues on the shader path.
  const int mode = m_vppFailed ? 0 : DVBRIDGE::playbackQsvMode.load();
  const bool elScaled = enhancement && enhancement->width < base.width && enhancement->height < base.height;
  const bool doBase = mode == 2 && base.vaDisplay && base.layout == DVBRIDGE_P010 && (!enhancement || elScaled);
  const bool doEnhancement = mode >= 1 && elScaled && (mode == 1 || doBase);
  dvbridge_dmabuf baseImported{}, elImported{};
  bool offloaded = false;
  if (doBase || doEnhancement)
  {
    if (!m_vpp)
      m_vpp = dvbridge_vpp_create();
    const char* reason = m_vpp ? nullptr : "allocation";
    if (!reason && doBase)
      reason = dvbridge_vpp_process(m_vpp, DVBRIDGE_VPP_BASE, base.vaDisplay, base.vaSurface, base.width,
                                    base.height, base.width, base.height, true, &baseImported);
    if (!reason && doEnhancement)
    {
      const auto* frames = enhancement->hw_frames_ctx
                               ? reinterpret_cast<const AVHWFramesContext*>(enhancement->hw_frames_ctx->data)
                               : nullptr;
      const auto* device = frames && frames->device_ctx
                               ? static_cast<const AVVAAPIDeviceContext*>(frames->device_ctx->hwctx)
                               : nullptr;
      if (enhancement->format != AV_PIX_FMT_VAAPI || !device || frames->sw_format != AV_PIX_FMT_P010)
        reason = "enhancement-format";
      else
        reason = dvbridge_vpp_process(
            m_vpp, DVBRIDGE_VPP_ENHANCEMENT, device->display,
            static_cast<unsigned>(reinterpret_cast<uintptr_t>(enhancement->data[3])), enhancement->width,
            enhancement->height, base.width, base.height, doBase, &elImported);
    }
    offloaded = reason == nullptr;
    if (!offloaded)
    {
      dvbridge_dmabuf_release(&baseImported);
      dvbridge_dmabuf_release(&elImported);
      m_vppFailed = true;
      dvbridge_vpp_release(m_vpp);
      CLog::Log(LOGWARNING, "DVBridge: Quick Sync scaling unavailable ({}), using GPU shaders", reason);
    }
    else if (!m_vppLogged)
    {
      m_vppLogged = true;
      CLog::Log(LOGINFO, "DVBridge: Quick Sync on the Intel media engine:{}{}",
                doBase ? " base layer colour" : "",
                doEnhancement ? " enhancement layer upscale" : "");
    }
  }
  Layer baseLayer = base;
  if (offloaded && doBase)
  {
    baseLayer.layout = DVBRIDGE_Y416_BASE_ROT180;
    baseLayer.planes[0] = baseImported.planes[0];
    baseLayer.planes[1] = baseLayer.planes[2] = {};
  }
  if (!enhancement)
  {
    const bool result = Prepare(baseLayer, nullptr, metadata, geometry, allowPacked);
    dvbridge_dmabuf_release(&baseImported);
    return result;
  }
  const bool elOffloaded = offloaded && doEnhancement;
  if (!elOffloaded && !dvbridge_dmabuf_import(&elImported, enhancement))
    return Failure("enhancement-dmabuf-import");
  Layer layer{};
  layer.layout = !elOffloaded ? elImported.layout : doBase ? DVBRIDGE_Y416_EL_ROT180 : DVBRIDGE_Y416;
  layer.width = elOffloaded ? elImported.planes[0].width : enhancement->width;
  layer.height = elOffloaded ? elImported.planes[0].height : enhancement->height;
  layer.pts = static_cast<double>(enhancement->pts);
  for (int i = 0; i < 3; ++i)
    layer.planes[i] = elImported.planes[i];
  bool result = Prepare(baseLayer, &layer, metadata, geometry, allowPacked);
  dvbridge_dmabuf_release(&elImported);
  dvbridge_dmabuf_release(&baseImported);
  return result;
}

void CDVBridgeGLES::CaptureOutput(unsigned int framebuffer, int width, int height, bool flipY)
{
  if (!m_captureOutputs || m_hdr10 || m_outputBits != 8 || framebuffer != 0 ||
      width != 3840 || height != 2160 || !flipY || m_outputCaptureMetadata.empty())
    return;
  const uint64_t now = DVBRIDGE::DiagnosticNowMs();
  if (!m_outputCaptureWaiting && now - m_lastOutputCapturePoll < 250)
    return;
  m_lastOutputCapturePoll = now;
  constexpr const char* request = "/storage/dvbridge-output-captures/request";
  struct stat status{};
  if (lstat(request, &status) || !S_ISREG(status.st_mode))
  {
    m_outputCaptureWaiting = false;
    return;
  }
  m_outputCaptureWaiting = true;
  double requestedPts = 0;
  int exact = 0;
  FILE* file = std::fopen(request, "r");
  if (!file)
    return;
  const bool parsed = std::fscanf(file, "%lf %d", &requestedPts, &exact) == 2;
  std::fclose(file);
  if (!parsed || !std::isfinite(requestedPts) || requestedPts < 0 ||
      (exact != 0 && exact != 1) || !std::isfinite(m_outputCapturePts) ||
      !std::isfinite(m_outputCaptureElPts) || m_outputCapturePts < requestedPts - 1000.0)
    return;
  char directory[] = "/storage/dvbridge-output-captures/frame-XXXXXX";
  if (!mkdtemp(directory))
    return;
  const std::string prefix = std::string(directory) + "/";
  if (std::rename(request, (prefix + "request").c_str()))
    return;
  m_outputCaptureWaiting = false;
  auto write = [&](const char* name, const void* data, size_t bytes) {
    FILE* output = std::fopen((prefix + name).c_str(), "wb");
    if (!output)
      return false;
    const bool written = std::fwrite(data, 1, bytes, output) == bytes;
    return std::fclose(output) == 0 && written;
  };
  const bool success = [&]() {
    if (exact && std::fabs(m_outputCapturePts - requestedPts) > 1000.0)
      return false;
    struct statvfs space{};
    if (statvfs(directory, &space) ||
        static_cast<uint64_t>(space.f_bavail) * space.f_frsize < 64ULL * 1024 * 1024)
      return false;
    constexpr size_t bytes = 3840ULL * 2160 * 4;
    std::unique_ptr<void, decltype(&std::free)> pixels(std::malloc(bytes), &std::free);
    if (!pixels)
      return false;
    GLint readFbo = 0, readBuffer = 0, packBuffer = 0, alignment = 0;
    GLint rowLength = 0, skipRows = 0, skipPixels = 0;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &readFbo);
    glGetIntegerv(GL_READ_BUFFER, &readBuffer);
    glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &packBuffer);
    glGetIntegerv(GL_PACK_ALIGNMENT, &alignment);
    glGetIntegerv(GL_PACK_ROW_LENGTH, &rowLength);
    glGetIntegerv(GL_PACK_SKIP_ROWS, &skipRows);
    glGetIntegerv(GL_PACK_SKIP_PIXELS, &skipPixels);
    if (glGetError() != GL_NO_ERROR)
      return false;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    glReadBuffer(GL_BACK);
    glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ROW_LENGTH, 0);
    glPixelStorei(GL_PACK_SKIP_ROWS, 0);
    glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.get());
    const GLenum error = glGetError();
    glBindFramebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(readFbo));
    glReadBuffer(static_cast<GLenum>(readBuffer));
    glBindBuffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(packBuffer));
    glPixelStorei(GL_PACK_ALIGNMENT, alignment);
    glPixelStorei(GL_PACK_ROW_LENGTH, rowLength);
    glPixelStorei(GL_PACK_SKIP_ROWS, skipRows);
    glPixelStorei(GL_PACK_SKIP_PIXELS, skipPixels);
    if (error != GL_NO_ERROR || glGetError() != GL_NO_ERROR ||
        !write("output.rgba", pixels.get(), bytes) ||
        !write("metadata.bin", m_outputCaptureMetadata.data(), m_outputCaptureMetadata.size()))
      return false;
    char info[512];
    int batchedPlanes = 0, immutableInstructions = 0;
#ifdef HAVE_YBLOD_NATIVE_PLAYBACK
    if (m_nativePrepared)
    {
      yb_native_playback_batch_stats batch{};
      yb_gpu_fp32_instruction_stats instruction{};
      instruction.version = 1;
      if (yb_native_playback_get_batch_stats(m_native, &batch) != YB_NATIVE_PLAYBACK_OK)
        return false;
      batchedPlanes = batch.selected ? 1 : 0;
      if (yb_native_playback_fp32_selected(m_native))
      {
        if (yb_native_playback_get_instruction_stats(m_native, &instruction, sizeof(instruction)) != YB_NATIVE_PLAYBACK_OK)
          return false;
        immutableInstructions = instruction.enabled ? 1 : 0;
      }
    }
#endif
    const int length = std::snprintf(info, sizeof(info),
        "{\"width\":3840,\"height\":2160,\"format\":\"RGBA8 DV tunnel bottom up\","
        "\"pts\":%.17g,\"el_pts\":%.17g,\"requested_pts\":%.17g,\"exact\":%d,"
        "\"native\":%d,\"direct_packed\":%d,\"qsv_mode\":%d,\"native_planar\":%d,"
        "\"batched_planes\":%d,\"immutable_instructions\":%d,"
        "\"el_decoder_qsv\":%d,\"el_qsv_map_sequence\":%llu,\"el_qsv_native_used\":%d}\n",
        m_outputCapturePts, m_outputCaptureElPts, requestedPts, exact,
        m_nativePrepared ? 1 : 0, m_direct ? 1 : 0, DVBRIDGE::playbackQsvMode.load(),
        m_nativePrepared && m_nativePlanarPrepared ? 1 : 0, batchedPlanes, immutableInstructions,
        m_elDecoderQsv ? 1 : 0, static_cast<unsigned long long>(m_elQsvMapSequence),
        m_nativePrepared && m_elQsvNativeUsed ? 1 : 0);
    return length > 0 && static_cast<size_t>(length) < sizeof(info) &&
           write("frame.json", info, static_cast<size_t>(length));
  }();
  CLog::Log(success ? LOGINFO : LOGERROR,
      "DVBridge output capture: success={} directory={} pts={} el_pts={} native={}",
      success, directory, m_outputCapturePts, m_outputCaptureElPts, m_nativePrepared);
}

bool CDVBridgeGLES::Pack(unsigned int framebuffer, int width, int height, bool flipY)
{
  m_packed = false;
  if (!m_prepared)
    return Failure("pack-without-prepared-frame");
  if (m_direct)
  {
    m_packed = framebuffer == 0 && width == 3840 && height == 2160 && flipY;
    if (m_packed)
      CaptureOutput(framebuffer, width, height, flipY);
    return m_packed || Failure("direct-pack-target");
  }
  unsigned int count;
  const auto* packets = dvbridge_packets(dvbridge_render_candidate(m_renderer), &count);
  m_packed = dvbridge_gl_pack(m_packer, GetPQTexture(), framebuffer, width, height,
                             packets, count, flipY);
  if (m_packed)
    CaptureOutput(framebuffer, width, height, flipY);
  return m_packed || Failure("composition-pack");
}

bool CDVBridgeGLES::ResolveHDR10(bool limited)
{
  m_packed = m_hdr10 && m_prepared &&
      dvbridge_render_hdr10(m_renderer, m_scanout, true, limited, m_outputBits);
  return m_packed || Failure("hdr10-resolve");
}

bool CDVBridgeGLES::PrepareGraphics(float whiteNits, double pts)
{
  m_prepared = m_packed = false;
  m_nativePrepared = false;
  m_direct = false;
  m_pendingInfo = 0;
  if (!m_renderer || !m_packer || m_hdr10)
    return Failure("graphics-unavailable");
  SetIptOffset(m_renderer, m_packer);
  // 0.005 cd/m2 black (the spec's default source minimum, as Amlogic's graphics minimum). The
  // average follows the static-metadata convention of midway between the scene limits.
  const unsigned black = PQCode(0.005f);
  const unsigned white = PQCode(whiteNits);
  m_graphicsWhite = whiteNits;
  m_prepared = white > black &&
               dvbridge_render_graphics(m_renderer, black, white, (black + white) / 2, pts);
  return m_prepared || Failure("graphics-prepare");
}

bool CDVBridgeGLES::PackGraphics(unsigned int guiTexture, unsigned int framebuffer, int width,
                                 int height, bool flipY, float saturation, unsigned gamma,
                                 bool wideColour)
{
  m_packed = false;
  if (!m_prepared)
    return Failure("pack-without-prepared-graphics");
  unsigned int count;
  const auto* packets = dvbridge_packets(dvbridge_render_candidate(m_renderer), &count);
  const dvbridge_graphics_style style{m_graphicsWhite, saturation, gamma, wideColour};
  m_packed = dvbridge_gl_pack_graphics(m_packer, guiTexture, framebuffer, width, height, packets,
                                       count, flipY, &style);
  return m_packed || Failure("graphics-pack");
}

unsigned int CDVBridgeGLES::GetPQFramebuffer()
{
  const auto texture = GetPQTexture();
  if (!texture)
    return 0;
  GLint previous;
  glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previous);
  if (!m_framebuffer)
    glGenFramebuffers(1, &m_framebuffer);
  glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_framebuffer);
  glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
  const bool valid = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previous);
  return valid ? m_framebuffer : 0;
}

bool CDVBridgeGLES::Presented(bool success)
{
  const bool committed = success && m_prepared && m_packed && dvbridge_render_commit(m_renderer);
  if (committed && m_nativePrepared)
  {
    ++m_nativePresented;
    if (m_nativePresented == 1 || m_nativePresented % 120 == 0)
      CLog::Log(LOGINFO, "DVBridge native reconstruction: presented={} colour=inherited-release colour_imports={}",
                m_nativePresented, m_nativeColourNoReimport ? "metadata-only" : "original-bl-el-reimport");
  }
  // A held frame during paced recovery is not a new presentation attempt.
  if (DVBRIDGE::DiagnosticsEnabled() && m_prepared)
  {
    m_presentations += committed;
    m_failedPresentations += !committed;
    if (!committed)
      Failure("presentation");
    // Coarse accounting only: no GPU queries, fences or readbacks added here.
    if ((m_presentations + m_failedPresentations) % 120 == 0)
    {
      const auto now = DVBRIDGE::DiagnosticNowMs();
      if (now - m_lastSummary >= 30000)
      {
        m_lastSummary = now;
        Summary("summary");
      }
    }
  }
  CDVPlaybackInfo::presented.store(committed ? m_pendingInfo : 0);
  if (!committed)
    dvbridge_renderer_reset(m_renderer);
  m_prepared = m_packed = false;
  m_nativePrepared = false;
  m_direct = false;
  return committed;
}
