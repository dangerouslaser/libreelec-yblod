"""Generic09 logger source guards only, not GPU or playback evidence."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
PATCH=ROOT/'projects/Generic/patches/kodi/kodi-9999-yblod-09-native-stage-timings.patch'
class KodiTimingPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source='\n'.join(line[1:] for line in PATCH.read_text().splitlines()
                             if line.startswith(('+',' ')) and not line.startswith('+++'))
    def test_environment_exact_one_and_default_off(self):
        requested=self.source.split('bool NativeTimingRequested()',1)[1].split('void LogNativeTimings(',1)[0]
        self.assertIn('std::getenv("DVBRIDGE_NATIVE_DIAGNOSTICS")',requested)
        self.assertIn('return value && std::strcmp(value, "1") == 0',requested)
        log=self.source.split('void LogNativeTimings(',1)[1]
        self.assertLess(log.index('if (!NativeTimingRequested())'),log.index('yb_native_playback_diagnostics_get('))
    def test_logger_current_version_initialization_validity_and_120_release_cadence(self):
        log=self.source.split('void LogNativeTimings(',1)[1].split('const auto perFrameMs',1)[0]
        # Current ABI always returns1. This guards the published initializer,
        # not a future returned-version rejection which is not implemented yet.
        for check in ('YB_NATIVE_PLAYBACK_OK','stats.version = 1','!stats.enabled','!stats.valid','!stats.completed_frames','stats.completed_frames % 120 != 0'):
            self.assertIn(check,log)
        self.assertIn('return;',log)
    def test_denominator_is_successful_release_not_attempt_or_display_count(self):
        per=self.source.split('const auto perFrameMs',1)[1].split('// Cumulative',1)[0]
        self.assertIn('stats.stages[stage].total_wall_ns',per)
        self.assertIn('static_cast<double>(stats.completed_frames) / 1000000.0',per)
        self.assertNotIn('m_nativePresented',per)
        self.assertNotIn('output_attempts',per)
        self.assertIn('wall_ms_per_released_frame',self.source)
        self.assertIn('Not GPU kernel time',self.source)
    def test_enable_is_after_create_and_nonfatal(self):
        s=self.source.split('const int status = yb_native_playback_create(',1)[1].split('yb_native_playback_frame request',1)[0]
        self.assertLess(s.index('if (status != YB_NATIVE_PLAYBACK_OK)'),s.index('yb_native_playback_diagnostics_enable('))
        enabled=s.split('if (NativeTimingRequested() &&',1)[1]
        self.assertIn('enable failed; playback unchanged',enabled)
        self.assertNotIn('return',enabled)
        self.assertNotIn('fail(',enabled)
    def test_logging_only_after_successful_release(self):
        released=self.source.split('const int released = yb_native_playback_release(',1)[1]
        self.assertLess(released.index('if (released != YB_NATIVE_PLAYBACK_OK)'),released.index('LogNativeTimings(m_native)'))
        self.assertLess(released.index('return fail("consumer-release", released)'),released.index('LogNativeTimings(m_native)'))
if __name__=='__main__':unittest.main()
