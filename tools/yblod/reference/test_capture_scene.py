import hashlib
import contextlib
import io
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import capture_scene as module
from test_observe_subtitle_fixture import MockPlayer


class Tests(unittest.TestCase):
    def args(self, *extra):
        return module.parse_args(['--config', '/unused/config', '--report', '/unused/report', *extra])

    def test_defaults_preserve_spr_capture(self):
        args = self.args()
        self.assertEqual((args.movie_id, args.expected_title, args.seek_seconds),
                         (3391, 'Saving Private Ryan', 1200))
        self.assertEqual(module.capture_targets(args), [(1210000000, 0), (1220000000, 0), (1230000000, 0)])
        self.assertFalse(args.subtitles_off)

    def test_subtitle_fixture_default_has_no_rpc_and_file_combination_refused(self):
        with patch.object(module, 'rpc') as rpc:
            with module.capture_fixtures(self.args(), 1) as record:
                self.assertEqual(record, (None, None))
            rpc.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.args('--file', '/storage/test.mkv', '--subtitles-off')

    def test_subtitle_fixture_restores_on_success_and_capture_error_before_stop(self):
        for failed in (False, True):
            player = MockPlayer()
            with patch.object(module, 'rpc', side_effect=player.rpc), patch.object(module.time, 'sleep'):
                try:
                    with module.capture_fixtures(self.args('--subtitles-off'), 1) as (_, record):
                        self.assertFalse(player.enabled)
                        if failed:
                            raise RuntimeError('capture failed')
                except RuntimeError as error:
                    self.assertTrue(failed)
                    self.assertEqual(str(error), 'capture failed')
            self.assertTrue(player.enabled)
            self.assertFalse(any(method == 'Player.Stop' for method, _ in player.calls))
            if not failed:
                module.validate_fixture(record, 3391)
        source = inspect.getsource(module.capture_started)
        self.assertLess(source.index('with capture_fixtures'), source.index("rpc('Player.Stop'"))
        self.assertLess(source.index('validate_fixture(subtitles'), source.index("rpc('Player.Stop'"))

    def test_subtitle_restore_precedes_zoom_restore_on_error(self):
        events = []
        player = MockPlayer()
        @contextlib.contextmanager
        def zoom(*_):
            try:
                yield {'before': 'mock'}
            finally:
                events.append(('zoom-restored', player.enabled))
        with patch.object(module, 'temporary_view_zoom', side_effect=zoom), \
             patch.object(module, 'rpc', side_effect=player.rpc), patch.object(module.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                with module.capture_fixtures(self.args('--subtitles-off', '--view-zoom', '0.9'), 1):
                    raise RuntimeError('capture failed')
        self.assertEqual(events, [('zoom-restored', True)])

    def test_failure_cleanup_disables_capture_and_stops_owned_service_even_rpc_failure(self):
        for rpc_failure in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                override = Path(directory)/'override'
                request = Path(directory)/'request'
                request.write_text('pending')
                previous = '[Service]\nEnvironment=OTHER=preserved\nEnvironment=DVBRIDGE_CAPTURE_OUTPUTS=1\n'
                commands = []
                def command(*args):
                    commands.append(args)
                    return 'active\n' if len(commands) == 1 else 'inactive\n'
                def rpc(method, params=None):
                    if rpc_failure:
                        raise RuntimeError('RPC unavailable')
                    return [dict(type='video', playerid=1)] if method == 'Player.GetActivePlayers' else 'OK'
                with patch.object(module, 'process_identity', return_value={'owned': True}), \
                     patch.object(module, 'command', side_effect=command), patch.object(module, 'rpc', side_effect=rpc):
                    if rpc_failure:
                        with self.assertRaisesRegex(RuntimeError, 'RPC unavailable'):
                            module.capture_failure_cleanup(override, previous, request, dict(started=True, identity={'owned': True}, player=1))
                    else:
                        module.capture_failure_cleanup(override, previous, request, dict(started=True, identity={'owned': True}, player=1))
                self.assertIn(('systemctl', 'stop', 'kodi'), commands)
                self.assertFalse(request.exists())
                restored = override.read_text()
                self.assertIn('Environment=OTHER=preserved', restored)
                for name in ('OUTPUTS', 'PAIRS'):
                    self.assertIn(f'Environment=DVBRIDGE_CAPTURE_{name}=0', restored)
                self.assertNotIn('DVBRIDGE_CAPTURE_OUTPUTS=1', restored)

    def test_failure_cleanup_refuses_changed_service_child(self):
        with tempfile.TemporaryDirectory() as directory:
            override = Path(directory)/'override'
            request = Path(directory)/'request'
            with patch.object(module, 'command', return_value='active\n') as command, \
                 patch.object(module, 'process_identity', return_value={'other': True}), patch.object(module, 'rpc') as rpc:
                with self.assertRaisesRegex(RuntimeError, 'process changed'):
                    module.capture_failure_cleanup(override, '[Service]\n', request, dict(started=True, identity={'owned': True}))
                command.assert_called_once()
                rpc.assert_not_called()
                self.assertFalse(override.exists())

    def test_other_movie_and_fractional_targets(self):
        args = self.args('--movie-id', '51', '--expected-title', '1917', '--seek-seconds', '60.5',
                         '--target-seconds', '71.25', '--target-seconds', '81.25')
        self.assertEqual(module.capture_targets(args), [(71250000, 0), (81250000, 0)])
        self.assertEqual(self.args('--seek-seconds', '0').target_seconds, [10, 20, 30])

    def test_file_item_identity_and_library_flow(self):
        args = self.args('--file', '/storage/numbered-test.mkv', '--seek-seconds', '0')
        self.assertEqual(module.open_item(args), {'file': '/storage/numbered-test.mkv'})
        with patch.object(module, 'rpc', return_value={'item': {'file': args.file}}) as rpc:
            module.verify_file_item(args, 1)
            rpc.assert_called_once_with('Player.GetItem', {'playerid': 1, 'properties': ['file']})
        with patch.object(module, 'rpc', return_value={'item': {'file': '/storage/wrong.mkv'}}):
            with self.assertRaises(RuntimeError):
                module.verify_file_item(args, 1)
        library = self.args('--movie-id', '51', '--expected-title', '1917')
        self.assertEqual(module.open_item(library), {'movieid': 51})
        with patch.object(module, 'rpc') as rpc:
            module.verify_file_item(library, 1)
            rpc.assert_not_called()

    def test_optional_optimization_route_gates_are_strict(self):
        old = dict(native=1, direct_packed=1)
        module.verify_capture_route(old, self.args())
        for field in ('batched_planes', 'immutable_instructions'):
            for expected in (0, 1):
                args = self.args('--expected-'+field.replace('_', '-'), str(expected))
                module.verify_capture_route(dict(old, **{field: expected}), args)
                for invalid in (old, dict(old, **{field: 1-expected}),
                                dict(old, **{field: bool(expected)})):
                    with self.assertRaises(RuntimeError):
                        module.verify_capture_route(invalid, args)

    def test_optional_planar_route_gate_is_strict_when_requested(self):
        old = dict(native=1, direct_packed=1)
        module.verify_capture_route(old, self.args())
        for expected in (0, 1):
            args = self.args('--expected-native', '1', '--expected-direct-packed', '1',
                             '--expected-native-planar', str(expected))
            module.verify_capture_route(dict(old, native_planar=expected), args)
            for invalid in (old, dict(old, native_planar=1-expected), dict(old, native_planar=bool(expected))):
                with self.assertRaises(RuntimeError):
                    module.verify_capture_route(invalid, args)

    def test_invalid_media_and_target_args(self):
        invalid = (('--movie-id', '0'), ('--expected-title', ''), ('--seek-seconds', 'nan'),
                   ('--seek-seconds', '-1'), ('--seek-seconds', '86401'),
                   ('--target-seconds', '1200'), ('--target-seconds', 'inf'),
                   ('--target-seconds', '1220', '--target-seconds', '1210'),
                   ('--baseline', '/unused/baseline', '--target-seconds', '1210'))
        invalid += (('--file', 'relative.mkv'), ('--file', '/storage/test.mkv', '--movie-id', '51'))
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
