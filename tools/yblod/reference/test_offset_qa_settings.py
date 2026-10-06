import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import offset_qa_settings as module


class Tests(unittest.TestCase):
    def run_helper(self, snapshot, before=True, restore=False, active=False, after=False,
                   update=True, state='inactive', expected_error=None):
        reads = iter((before, after))
        def rpc(method, params=None):
            if method == 'Player.GetActivePlayers':
                return [{'playerid': 1}] if active else []
            if method == 'Settings.GetSettingValue':
                return {'value': next(reads)}
            if method == 'Settings.SetSettingValue':
                return update
            raise AssertionError(method)
        def command(*args):
            if args[-1] == '--value':
                return state
            if args[1] == 'show':
                return 'ActiveState=inactive\nResult=success\nMainPID=0\n'
            return ''
        argv = ['offset_qa_settings.py', '--snapshot', str(snapshot)] + (['--restore'] if restore else [])
        output = io.StringIO()
        with patch('sys.argv', argv), patch.object(module, 'rpc', side_effect=rpc) as rpc_mock, \
             patch.object(module, 'command', side_effect=command) as command_mock, \
             patch.object(module, 'wait_rpc'), patch.object(module.time, 'sleep'), \
             contextlib.redirect_stdout(output):
            if expected_error:
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    module.main()
            else:
                module.main()
        return rpc_mock, command_mock, output.getvalue()

    def test_snapshot_preserves_original_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            for original in (False, True):
                path = Path(directory) / str(original)
                rpc, _, output = self.run_helper(path, before=original)
                self.assertEqual(json.loads(path.read_text()),
                    dict(setting='dvbridge.matchhardware', original=original))
                self.assertIn(unittest.mock.call('Settings.SetSettingValue',
                    {'setting': 'dvbridge.matchhardware', 'value': False}), rpc.call_args_list)
                self.assertEqual(json.loads(output)['after'], False)

    def test_restore_uses_saved_original_not_current_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            for original in (False, True):
                path.write_text(json.dumps(dict(setting='dvbridge.matchhardware', original=original)))
                rpc, _, output = self.run_helper(path, before=not original, restore=True, after=original)
                self.assertIn(unittest.mock.call('Settings.SetSettingValue',
                    {'setting': 'dvbridge.matchhardware', 'value': original}), rpc.call_args_list)
                self.assertEqual(json.loads(output)['after'], original)
                self.assertTrue(json.loads(output)['restored'])

    def test_active_player_and_wrong_setting_type_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            for kwargs, message in ((dict(active=True), 'idle Kodi'),
                                    (dict(before=1), 'setting type')):
                rpc, _, _ = self.run_helper(path, expected_error=message, **kwargs)
                self.assertFalse(path.exists())
                self.assertFalse(any(call.args[0] == 'Settings.SetSettingValue' for call in rpc.call_args_list))

    def test_bad_restore_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            for saved in (dict(setting='wrong', original=True),
                          dict(setting='dvbridge.matchhardware', original=1), {}):
                path.write_text(json.dumps(saved))
                rpc, _, _ = self.run_helper(path, restore=True, expected_error='Invalid settings snapshot')
                self.assertFalse(any(call.args[0] == 'Settings.SetSettingValue' for call in rpc.call_args_list))

    def test_failed_update_and_readback_refused_snapshot_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, kwargs in enumerate((dict(update=False), dict(after=True))):
                path = Path(directory) / str(index)
                _, _, _ = self.run_helper(path, expected_error='update failed|verification failed', **kwargs)
                self.assertEqual(json.loads(path.read_text())['original'], True)

    def test_running_service_or_existing_snapshot_refused_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            _, command, _ = self.run_helper(path, state='active', expected_error='cleanly stopped')
            self.assertNotIn(unittest.mock.call('systemctl', 'start', 'kodi'), command.call_args_list)
            path.write_text('{}')
            _, command, _ = self.run_helper(path, expected_error='Fresh settings snapshot')
            self.assertNotIn(unittest.mock.call('systemctl', 'start', 'kodi'), command.call_args_list)


if __name__ == '__main__':
    unittest.main()
