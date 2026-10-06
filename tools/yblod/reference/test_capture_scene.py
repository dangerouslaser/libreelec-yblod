import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import capture_scene as module


class Tests(unittest.TestCase):
    def test_identity_pins_process_start_and_actual_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / '123'
            proc.mkdir()
            binary = b'diagnostic executable'
            (proc / 'exe').write_bytes(binary)
            (proc / 'comm').write_text('kodi.bin\n')
            fields = ['0'] * 20
            fields[0] = 'S'
            fields[1] = '100'
            fields[19] = '45678'
            (proc / 'stat').write_text('123 (Kodi binary) ' + ' '.join(fields))
            with patch.object(module, 'command', return_value='100\n'), \
                 patch.object(module, 'Path', return_value=root):
                self.assertEqual(module.process_identity(), dict(service_pid=100, pid=123, start_ticks=45678,
                    binary_sha256=hashlib.sha256(binary).hexdigest()))

    def test_missing_or_ambiguous_child_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(module, 'command', return_value='100\n'), \
                 patch.object(module, 'Path', return_value=root):
                with self.assertRaises(RuntimeError):
                    module.process_identity()
                for pid in (123, 124):
                    proc = root / str(pid)
                    proc.mkdir()
                    (proc / 'comm').write_text('kodi.bin\n')
                    fields = ['0'] * 20
                    fields[0] = 'S'
                    fields[1] = '100'
                    fields[19] = '45678'
                    (proc / 'stat').write_text(str(pid) + ' (kodi.bin) ' + ' '.join(fields))
                with self.assertRaises(RuntimeError):
                    module.process_identity()

    def test_inactive_process_rejected(self):
        with patch.object(module, 'command', return_value='0\n'):
            with self.assertRaises(RuntimeError):
                module.process_identity()


if __name__ == '__main__':
    unittest.main()
