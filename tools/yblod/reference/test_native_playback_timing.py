"""Additive host-wall diagnostics source guards; no GPU operations."""
import json,os,subprocess
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
class PlaybackTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'engine/experimental/native_playback_context.c').read_text()
        cls.header=(ROOT/'engine/experimental/native_playback_context.h').read_text()
    def test_default_disabled_before_clock_and_same_owner_thread(self):
        begin=self.source.split('static yb_timing_mark timing_begin(',1)[1].split('static int timing_accumulate(',1)[0]
        self.assertLess(begin.index('!p->diagnostics.enabled'),begin.index('timing_now('))
        self.assertIn('Same owner thread',self.header)
        self.assertIn('NOT atomic or thread-safe',self.header)
    def test_all_eleven_stages_and_correct_helper_status_enums(self):
        for stage in ('SCALER_SUBMIT','VA_WAIT','IMPORT','PREPARATION_SUBMIT','PREPARATION_WAIT','COMPOSER_SUBMIT','COMPOSER_WAIT','YCC_SUBMIT','YCC_WAIT','BRIDGE','RELEASE'):
            self.assertIn('YB_NATIVE_TIMING_'+stage,self.source)
        self.assertIn('YB_VPP_OK,YB_VPP_PENDING',self.source)
        self.assertIn('YB_GPU_BACKEND_OK,YB_GPU_BACKEND_PENDING',self.source)
        self.assertIn('YB_NATIVE_PLAYBACK_OK,YB_NATIVE_PLAYBACK_PENDING',self.source)
        self.assertIn('YB_VA_IMPORT_OK',self.source)
        self.assertIn('YB_EGL_BRIDGE_OK',self.source)
    def test_checked_stats_only_failure_and_public_query_contract(self):
        accumulate=self.source.split('static int timing_accumulate(',1)[1].split('static void timing_end(',1)[0]
        for guard in ('entry->calls==UINT64_MAX','UINT64_MAX-elapsed','*counter==UINT64_MAX'):
            self.assertIn(guard,accumulate)
        timing=self.source.split('typedef struct { uint64_t ns;',1)[1].split('static yb_gpu_proc get_proc(',1)[0]
        self.assertNotIn('quarantine(',timing)
        self.assertNotIn('egl',timing)
        self.assertNotIn('vaSync',timing)
        self.assertIn('if (status==YB_NATIVE_PLAYBACK_OK) timing_completed(p)',self.source)
        for api in ('enable','get','reset'):
            self.assertIn('yb_native_playback_diagnostics_'+api,self.header)
    def test_create_and_frame_abi_not_extended(self):
        settings=self.header.split('typedef struct { const char *bytes;',1)[1].split('} yb_native_playback_create_info;',1)[0]
        frame=self.header.split('} yb_native_playback_create_info;',1)[1].split('} yb_native_playback_frame;',1)[0]
        self.assertNotIn('diagnostics',settings)
        self.assertNotIn('diagnostics',frame)
        self.assertIn('info->version!=2',self.source)
    def test_probe_is_synthetic_no_gpu_and_disabled_clock_assertion(self):
        probe=(ROOT/'engine/experimental/native_playback_timing_probe.c').read_text()
        self.assertIn('#define clock_gettime yb_test_clock',probe)
        self.assertIn('!timing_begin(&p).active && clock_calls==0',probe)
        self.assertIn('entry.calls=UINT64_MAX',probe)
        self.assertIn('completed_frames=UINT64_MAX',probe)
        self.assertNotIn('eglCreate',probe)
        self.assertNotIn('vaCreate',probe)
    def test_optional_actual_sdk_probe(self):
        binary=os.environ.get('YB_NATIVE_PLAYBACK_TIMING_PROBE')
        if not binary:self.skipTest('set actual SDK host-only timing probe with matching runtime')
        p=json.loads(subprocess.run([binary],check=True,capture_output=True,text=True,timeout=5).stdout)
        self.assertFalse(p['gpu_attempted'])
        self.assertTrue(p['clock_is_synthetic'])
        self.assertGreaterEqual(p['checks_passed'],32)
    def test_saved_host_evidence_is_not_performance_proof(self):
        p=json.loads((ROOT/'tools/yblod/reference/results/native-playback-timing-host-20261006v.json').read_text())
        self.assertFalse(p['default_enabled'] or p['gpu_attempted'] or p['hardware_calls'] or p['resource_counters_captured'])
        self.assertTrue(p['strict_sdk_compile'] and p['whole_archive_sdk_link_passed'] and p['create_and_frame_layouts_unchanged'])
        self.assertEqual((p['diagnostics_version'],p['stage_count'],p['synthetic_result']['checks_passed']),(1,11,34))
        self.assertTrue(p['synthetic_result']['clock_is_synthetic'])
        self.assertEqual(p['probe_executable_sha256'],'497e32ddb7da1e1c0e7da59ae89f61bb40a112926ff4c964056b4c7038eb47c2')
        for value in p['tested_source_sha256'].values():self.assertRegex(value,r'^[0-9a-f]{64}$')
if __name__=='__main__':unittest.main()
