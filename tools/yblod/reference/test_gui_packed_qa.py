import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

import gui_packed_qa as module


IDENTITY = dict(service_pid=100, pid=123, start_ticks=456, binary_sha256='a'*64)
STOPPED = dict(ActiveState='inactive', Result='success', MainPID='0', ExecMainCode='1', ExecMainStatus='0')


def config_text():
    return (Path(__file__).with_name('native-packed-1.conf').read_text()
            .replace('DVBRIDGE_CAPTURE_OUTPUTS=0', 'DVBRIDGE_CAPTURE_OUTPUTS=1'))


def frame_info(direct):
    return dict(width=3840, height=2160, format='RGBA8 DV tunnel bottom up', pts=1210000000,
                el_pts=1210000000, requested_pts=0, exact=0, native=1, direct_packed=direct, qsv_mode=1)


def write_frame(folder, direct):
    folder.mkdir()
    info = frame_info(direct)
    with (folder/'output.rgba').open('wb') as output:
        output.truncate(module.RGBA_BYTES)
    (folder/'metadata.bin').write_bytes(b'test metadata, not film data')
    (folder/'frame.json').write_text(json.dumps(info))
    return info


class Tests(unittest.TestCase):
    def test_config_hash_and_fresh_report_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root/'capture.conf'
            config.write_text(config_text())
            report = root/'qa.json'
            argv = ['--config', str(config), '--binary-sha256', 'a'*64, '--report', str(report)]
            self.assertFalse(module.parse_args(argv).debug_overlay)
            self.assertTrue(module.parse_args(argv+['--debug-overlay']).debug_overlay)
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    module.parse_args(argv+['--binary-sha256', 'abc'])
                for changed in (config_text().replace('DVBRIDGE_NATIVE_PACKED_OUTPUT=1', 'DVBRIDGE_NATIVE_PACKED_OUTPUT=0'),
                                config_text()+'Environment=DVBRIDGE_CAPTURE_PAIRS=1\n',
                                config_text()+'Environment=DVBRIDGE_NATIVE_FP32=0\n'):
                    config.write_text(changed)
                    with self.assertRaises(SystemExit):
                        module.parse_args(argv)
                config.write_text(config_text())
                report.touch()
                with self.assertRaises(SystemExit):
                    module.parse_args(argv)

    def test_capture_frame_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'frame-test'
            info = write_frame(folder, 1)
            module.validate_frame(folder, info, 1)
            for key, value in (('direct_packed', 0), ('native', 0), ('qsv_mode', 2),
                               ('pts', float('nan')), ('el_pts', 0), ('width', 1920), ('exact', 1)):
                with self.assertRaises(RuntimeError):
                    module.validate_frame(folder, dict(info, **{key: value}), 1)
            (folder/'metadata.bin').write_bytes(b'')
            with self.assertRaises(RuntimeError):
                module.validate_frame(folder, info, 1)

    def test_window_transition_and_identity_gates(self):
        with patch.object(module, 'current_window', side_effect=[dict(id=1), dict(id=module.OSD), dict(id=module.OSD)]), \
             patch.object(module.time, 'sleep'):
            self.assertEqual(module.wait_window(module.OSD)['id'], module.OSD)
        with patch.object(module, 'process_identity', return_value=IDENTITY):
            self.assertEqual(module.check_identity(IDENTITY), IDENTITY)
        with patch.object(module, 'process_identity', return_value=dict(IDENTITY, start_ticks=999)):
            with self.assertRaises(RuntimeError):
                module.check_identity(IDENTITY)

    def test_next_request_and_capture_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def produce(_):
                if not (root/'frame-next').exists() and (root/'request').exists():
                    self.assertEqual((root/'request').read_text(), '0 0\n')
                    (root/'request').unlink()
                    write_frame(root/'frame-next', 1)
            with patch.object(module, 'CAPTURES', root), \
                 patch.object(module, 'check_identity', return_value=IDENTITY), \
                 patch.object(module, 'current_window', return_value=dict(id=module.FULLSCREEN)), \
                 patch.object(module.time, 'sleep', side_effect=produce):
                captured = module.capture_next('packed', 1, module.FULLSCREEN, IDENTITY)
            self.assertEqual(captured['frame']['direct_packed'], 1)
            self.assertEqual(captured['identity'], IDENTITY)

    def run_mocked(self, root, debug=False, capture_error=None):
        config, override, captures = root/'capture.conf', root/'override.conf', root/'captures'
        config.write_text(config_text())
        override.write_bytes(b'original config\n')
        captures.mkdir()
        args = argparse.Namespace(config=config, binary_sha256='a'*64, report=root/'qa.json', debug_overlay=debug)
        def rpc(method, params=None):
            if method == 'Player.GetActivePlayers':
                return []
            if method == 'VideoLibrary.GetMovieDetails':
                return dict(moviedetails=dict(title='Saving Private Ryan'))
            return 'OK'
        def capture(label, direct, window, identity):
            if capture_error:
                raise RuntimeError(capture_error)
            return dict(label=label, directory='/private/test-only', frame=frame_info(direct),
                        window_before=dict(id=window), window_after=dict(id=window), identity=identity)
        with patch.object(module, 'CAPTURES', captures), patch.object(module, 'OVERRIDE', override), \
             patch.object(module, 'service_state', return_value=STOPPED), \
             patch.object(module.shutil, 'disk_usage', return_value=argparse.Namespace(free=1024**3)), \
             patch.object(module, 'command') as commands, patch.object(module, 'rpc', side_effect=rpc) as calls, \
             patch.object(module, 'wait_idle'), patch.object(module, 'wait_player', return_value=1), \
             patch.object(module, 'wait_window'), patch.object(module, 'current_window', return_value=dict(id=module.FULLSCREEN)), \
             patch.object(module, 'process_identity', return_value=IDENTITY), \
             patch.object(module, 'capture_next', side_effect=capture), patch.object(module.time, 'sleep'):
            if capture_error:
                with self.assertRaises(RuntimeError):
                    module.run(args)
                self.assertNotIn(call('systemctl', 'stop', 'kodi'), commands.call_args_list)
            else:
                module.run(args)
                self.assertIn(call('systemctl', 'stop', 'kodi'), commands.call_args_list)
        self.assertEqual(override.read_bytes(), b'original config\n')
        return json.loads(args.report.read_text()), calls.call_args_list

    def test_successful_gui_routes_clean_stop_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            report, calls = self.run_mocked(Path(temp))
            self.assertEqual(report['status'], 'passed')
            self.assertEqual([row['frame']['direct_packed'] for row in report['captures']], [1, 0, 1])
            self.assertEqual(calls.count(call('Input.ShowOSD')), 2)
            self.assertEqual(report['identity_before'], report['identity_after'])
            self.assertEqual(report['shutdown'], STOPPED)
            self.assertIn(call('Player.Open', {'item': {'movieid': 3391}, 'options': {'resume': False}}), calls)
            self.assertIn(call('Player.Stop', {'playerid': 1}), calls)

    def test_optional_debug_overlay_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            report, calls = self.run_mocked(Path(temp), debug=True)
            self.assertEqual([row['frame']['direct_packed'] for row in report['captures']], [1, 0, 1, 0, 1])
            self.assertEqual(calls.count(call('Input.ExecuteAction', {'action': 'playerdebug'})), 2)

    def test_failure_preserves_evidence_without_force_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            report, calls = self.run_mocked(Path(temp), capture_error='wrong captured route')
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['failure'], 'wrong captured route')
            self.assertFalse(report['captures'])
            self.assertNotIn(call('Player.Stop', {'playerid': 1}), calls)


if __name__ == '__main__':
    unittest.main()
