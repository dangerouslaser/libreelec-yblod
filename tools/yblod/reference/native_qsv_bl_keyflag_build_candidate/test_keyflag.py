import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_keyflag as k


class Pins(unittest.TestCase):
    def test_report_separates_base_and_rejects_stale_identity(self):
        report = {'schema': 'base', 'compatible_param_patch_sha256': 'basepatch',
                  'qsvdec_sha256': k.OLD['qsvdec.c'], 'configuration_sha256': {},
                  'native_source_and_abi_sha256': {}, 'resources': 'old',
                  'qsv_dovi_header_sha256': 'old', 'extra_source_claim': 'old'}
        result = k.result_identity(report)
        self.assertEqual(result['base_provenance']['qsvdec_sha256'], k.OLD['qsvdec.c'])
        self.assertNotIn('resources', result)
        self.assertNotIn('extra_source_claim', result)
        self.assertNotIn('compatible_param_patch_sha256', result)
        for field in ('qsvdec_sha256', 'qsv_dovi_header_sha256', 'source_sha256'):
            stale = dict(result)
            stale[field] = 'stale'
            with self.assertRaises(AssertionError):
                k.validate_result_identity(stale)

    def test_only_two_private_source_changes(self):
        self.assertEqual(set(k.OLD), {'qsv_dovi.h', 'qsvdec.c'})
        self.assertEqual(set(k.OLD), set(k.NEW))
        self.assertTrue(all(k.OLD[n] != k.NEW[n] for n in k.OLD))

    def test_guard_never_skips_other_libraries(self):
        report = {'configuration_sha256': {}, 'native_source_and_abi_sha256': {},
                  'libraries': {'libavutil/libavutil.so.61': {'sha256': 'bad', 'bytes': 0}}}
        def digest(path):
            return k.NEW.get(path.name, 'changed')
        with patch.object(k.s, 'digest', side_effect=digest):
            with self.assertRaises(AssertionError):
                k.guards(Path('/unused'), report, changed=True, built=True)

    def test_guard_pins_native_abi(self):
        report = {'configuration_sha256': {}, 'native_source_and_abi_sha256': {'libavcodec/version_major.h': 'wanted'}, 'libraries': {}}
        with patch.object(k.s, 'digest', return_value='changed'):
            with self.assertRaises(AssertionError):
                k.guards(Path('/unused'), report, changed=True, built=True)


if __name__ == '__main__':
    unittest.main()
