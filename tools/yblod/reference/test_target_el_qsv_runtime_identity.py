from pathlib import Path
import unittest
from unittest.mock import patch
from prepare_target_el_qsv_runtime_identity import closure, needed_names


class TargetClosureTests(unittest.TestCase):
    def test_actual_target_elfutils_and_gnu_formats(self):
        self.assertEqual(needed_names('  NEEDED            Shared library: [libva.so.2]'),['libva.so.2'])
        self.assertEqual(needed_names(' 0x0000000000000001 (NEEDED) Shared library: [libva.so.2]'),['libva.so.2'])
        with self.assertRaises(ValueError):needed_names(' NEEDED unrecognized library syntax')
        self.assertEqual(needed_names(' SONAME Library soname: [libva.so.2]'),[])

    def fixture(self, data=None, exists=True, resolve=None, driver='/usr/lib/dri/iHD_drv_video.so'):
        def dynamic(argv,**unused):
            if data is not None:return data
            return '' if argv[-1].endswith(('libc.so.6','ld-linux-x86-64.so.2')) else ' NEEDED Shared library: [libc.so.6]'
        return (patch('prepare_target_el_qsv_runtime_identity.shutil.which',return_value='/usr/bin/readelf'),
                patch.object(Path,'resolve',resolve or (lambda p,strict=True:p)),
                patch.object(Path,'is_file',return_value=True),
                patch.object(Path,'exists',return_value=exists),
                patch('prepare_target_el_qsv_runtime_identity.subprocess.check_output',side_effect=dynamic),
                patch('prepare_target_el_qsv_runtime_identity.code_fingerprint',return_value=((1,2,3,4,5),'a'*64)))

    def run_fixture(self, **kwargs):
        from contextlib import ExitStack
        with ExitStack() as stack:
            mocks=[stack.enter_context(item) for item in self.fixture(**kwargs)]
            return closure('/runtime',kwargs.get('driver','/usr/lib/dri/iHD_drv_video.so'),'/usr/lib/ld-linux-x86-64.so.2'),mocks[-1].call_count

    def test_roots_and_cache_aware_stream_fingerprint(self):
        result,calls=self.run_fixture()
        self.assertEqual(len(result['files']),8)
        self.assertEqual(calls,8)
        self.assertEqual(result['files']['libvpl.so.2']['path'],'/runtime/libvpl.so.2')
        self.assertEqual(result['files']['iHD_drv_video.so']['path'],'/usr/lib/dri/iHD_drv_video.so')
        self.assertEqual(result['files']['ld-linux-x86-64.so.2']['path'],'/usr/lib/ld-linux-x86-64.so.2')

    def test_missing_dependency_rejected(self):
        with self.assertRaises(ValueError):self.run_fixture(data='(NEEDED) Shared library: [libmissing.so.1]',exists=False)

    def test_empty_known_runtime_dependencies_rejected(self):
        with self.assertRaises(ValueError):self.run_fixture(data='')

    def test_foreign_dependency_rejected(self):
        def resolve(path,strict=True):
            return Path('/foreign/libbad.so.1') if path==Path('/runtime/libbad.so.1') else path
        with self.assertRaises(ValueError):self.run_fixture(data='(NEEDED) Shared library: [libbad.so.1]',resolve=resolve)

    def test_absolute_dependency_rejected(self):
        with self.assertRaises(ValueError):self.run_fixture(data='(NEEDED) Shared library: [/foreign/libbad.so.1]')

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):self.run_fixture(driver='/usr/lib/libavcodec.so.63')

    def test_readelf_preflight(self):
        with patch('prepare_target_el_qsv_runtime_identity.shutil.which',return_value=None):
            with self.assertRaises(ValueError):closure('/runtime','/driver','/loader')


if __name__=='__main__':unittest.main()
