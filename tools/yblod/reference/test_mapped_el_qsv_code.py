import unittest
from pathlib import Path
from unittest.mock import patch
from collect_el_qsv_target_identity import is_mapped_code, mapped_libraries


class MappedCodeTests(unittest.TestCase):
    def test_cache_data_only(self):
        self.assertFalse(is_mapped_code('/etc/ld.so.cache', 'r--p'))
        self.assertTrue(is_mapped_code('/etc/ld.so.cache', 'r-xp'))
        self.assertTrue(is_mapped_code('/other/unknown.so.cache', 'r--p'))

    def test_real_code_names(self):
        for name in ('liba.so', 'liba.so.1.2', 'liba.so.debug', 'odd.so.suffix'):
            self.assertTrue(is_mapped_code(name, 'r--p'))
        self.assertTrue(is_mapped_code('/unknown/extensionless', 'r-xp'))
        self.assertFalse(is_mapped_code('/data/ordinary', 'r--p'))

    def test_unknown_code_rejected(self):
        for path, perms in (('/unknown/liba.so.1', 'r--p'),
                            ('/unknown/code', 'r-xp'),
                            ('/etc/ld.so.cache', 'r-xp'),
                            ('/allowed/liba.so.1 (deleted)', 'r--p')):
            with self.subTest(path=path), patch.object(Path, 'read_text', return_value=f'0-1 {perms} 0 0 0 {path}'), patch.object(Path, 'resolve', lambda p, strict=True: p):
                with self.assertRaises(ValueError):
                    mapped_libraries(1, {'a':'/allowed/liba.so.1'}, '/allowed/iHD_drv_video.so')

    def test_cache_excluded_complete_closure_probe_verified(self):
        names = ('libavcodec.so.63', 'libavformat.so.63', 'libavutil.so.61',
                 'libvpl.so.2', 'libmfx-gen.so.1', 'iHD_drv_video.so')
        files = {name:'/sdk/'+name for name in names}
        rows = [f'0-1 r--p 0 0 0 {path}' for path in files.values()]
        rows += ['0-1 r--p 0 0 0 /etc/ld.so.cache', '0-1 r-xp 0 0 0 /probe/binary']
        with patch.object(Path, 'read_text', return_value='\n'.join(rows)), patch.object(Path, 'resolve', lambda p, strict=True: p):
            self.assertTrue(mapped_libraries(1, files, files[names[-1]], verified_probe='/probe/binary'))
            with self.assertRaises(ValueError):
                mapped_libraries(1, files, files[names[-1]])

    def test_deleted_verified_probe_rejected(self):
        with patch.object(Path, 'read_text', return_value='0-1 r-xp 0 0 0 /probe/binary (deleted)'), patch.object(Path, 'resolve', lambda p, strict=True: p):
            with self.assertRaises(ValueError):
                mapped_libraries(1, {}, '/sdk/iHD_drv_video.so', verified_probe='/probe/binary')


if __name__ == '__main__':
    unittest.main()
