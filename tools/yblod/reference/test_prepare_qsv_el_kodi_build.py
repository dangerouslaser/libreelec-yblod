import unittest
import tempfile
from pathlib import Path
from prepare_qsv_el_kodi_build import serial_link, validate_final_command, validate_prepared, FILES, NEW, ENGINE, digest

class LinkTests(unittest.TestCase):
    def test_existing_flags_only_final_edge_changes(self):
        original = ('build another: CXX_EXECUTABLE_LINKER__other_Release x\n'
                    '  FLAGS = -flto=7\n  LINK_FLAGS = -s\n\n'
                    'build kodi.bin: CXX_EXECUTABLE_LINKER__kodi_Release x\n'
                    '  FLAGS = -flto=7\n  LINK_FLAGS = -s\n\n'
                    'build object: cc x\n  FLAGS = -flto=7\n')
        self.assertEqual(serial_link(original), original.replace(
            '  LINK_FLAGS = -s\n\nbuild object:',
            '  LINK_FLAGS = -s -flto=1\n\nbuild object:'))
    def test_absent_flags(self):
        original = 'build kodi.bin: CXX_EXECUTABLE_LINKER__kodi_Release x\n  FLAGS = -flto=7\n'
        self.assertIn('  LINK_FLAGS = -flto=1\n', serial_link(original))
    def test_ambiguous_fail_closed(self):
        for text in ('', 'build kodi.bin: other x\n',
                     'build kodi.bin: CXX_EXECUTABLE_LINKER__kodi_Release x\n'
                     '  LINK_FLAGS = x\n  LINK_FLAGS = y\n'):
            with self.assertRaises(ValueError): serial_link(text)
    def test_final_command_gate(self):
        validate_final_command('g++ -flto=7 -flto=1 x -o kodi.bin y')
        for command in ('g++ -flto=1 -flto=7 x -o kodi.bin y', '',
                        'g++ -flto=1 -o kodi.bin y\ng++ -flto=1 -o kodi.bin z'):
            with self.assertRaises(ValueError): validate_final_command(command)
    def test_prepared_source_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proof = {'source_applied': True, 'isolated_source_sha256': {}, 'engine_sha256': {}}
            for name in (*FILES, NEW):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name); proof['isolated_source_sha256'][name] = digest(path)
            for name in ENGINE:
                path = root / 'tools/native_engine/experimental' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name); proof['engine_sha256'][name] = digest(path)
            validate_prepared(root, proof)
            proof['source_applied'] = False
            with self.assertRaises(ValueError): validate_prepared(root, proof)
            proof['source_applied'] = True
            (root / FILES[0]).write_text('changed')
            with self.assertRaises(ValueError): validate_prepared(root, proof)

if __name__ == '__main__': unittest.main()
