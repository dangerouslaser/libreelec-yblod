import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import capture_scene as module


class Tests(unittest.TestCase):
    def args(self, *extra):
        return module.parse_args(['--config', '/unused/config', '--report', '/unused/report', *extra])

    def test_defaults_preserve_spr_capture(self):
        args = self.args()
        self.assertEqual((args.movie_id, args.expected_title, args.seek_seconds),
                         (3391, 'Saving Private Ryan', 1200))
        self.assertEqual(module.capture_targets(args), [(1210000000, 0), (1220000000, 0), (1230000000, 0)])

    def test_other_movie_and_fractional_targets(self):
        args = self.args('--movie-id', '51', '--expected-title', '1917', '--seek-seconds', '60.5',
                         '--target-seconds', '71.25', '--target-seconds', '81.25')
        self.assertEqual(module.capture_targets(args), [(71250000, 0), (81250000, 0)])
        self.assertEqual(self.args('--seek-seconds', '0').target_seconds, [10, 20, 30])

    def test_invalid_media_and_target_args(self):
        invalid = (('--movie-id', '0'), ('--expected-title', ''), ('--seek-seconds', 'nan'),
                   ('--seek-seconds', '-1'), ('--seek-seconds', '86401'),
                   ('--target-seconds', '1200'), ('--target-seconds', 'inf'),
                   ('--target-seconds', '1220', '--target-seconds', '1210'),
                   ('--baseline', '/unused/baseline', '--target-seconds', '1210'))
        with contextlib.redirect_stderr(io.StringIO()):
            for extra in invalid:
                with self.assertRaises(SystemExit):
                    self.args(*extra)

    def test_exact_baseline_pts_unchanged_and_invalid_values_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / 'baseline.json'
            args = self.args('--baseline', str(baseline))
            values = [1210012345.75, 1220012345.75, 1230012345.75]
            baseline.write_text(json.dumps(dict(frames=[dict(pts=value) for value in values])))
            self.assertEqual(module.capture_targets(args), [(value, 1) for value in values])
            for invalid in ([], [float('nan')], [True], [1200000000], [1220000000, 1210000000]):
                baseline.write_text(json.dumps(dict(frames=[dict(pts=value) for value in invalid])))
                with self.assertRaises(RuntimeError):
                    module.capture_targets(args)

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
