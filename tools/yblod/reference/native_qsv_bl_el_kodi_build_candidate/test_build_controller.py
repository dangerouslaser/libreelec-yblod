"""No Docker, compiler or GPU activity: exercise controller safety boundaries."""
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import prepare_build_qsv_kodi as controller

CID = 'a' * 64


def state(running=False):
    return {'Id': CID, 'Image': controller.IMAGE,
            'State': {'Running': running, 'Restarting': False,
                      'Status': 'running' if running else 'exited', 'ExitCode': 1, 'OOMKilled': False}}


class ControllerTests(unittest.TestCase):
    def test_cli_default_is_bounded(self):
        with patch.object(controller.subprocess, 'run') as invoked:
            controller.run(['docker', 'inspect', CID])
            self.assertEqual(invoked.call_args.kwargs['timeout'], 30)

    def test_wrong_owned_id_rejected(self):
        value = state()
        value['Id'] = 'b' * 64
        with patch.object(controller, 'run', return_value=Mock(stdout=json.dumps([value]))):
            with self.assertRaises(AssertionError):
                controller.inspect_owned(CID)

    def test_wrong_image_rejected(self):
        value = state()
        value['Image'] = 'sha256:other'
        with patch.object(controller, 'run', return_value=Mock(stdout=json.dumps([value]))):
            with self.assertRaises(AssertionError):
                controller.inspect_owned(CID)

    def test_stop_timeout_uses_exact_id_kill_then_wait(self):
        calls = []
        def fake(args, **kwargs):
            calls.append((args, kwargs))
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 25)
            self.assertEqual(args[-1], CID)
            if args[1] == 'stop':
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            return Mock(stdout='1')
        with patch.object(controller, 'inspect_owned', side_effect=[state(True), state()]), \
             patch.object(controller, 'run', side_effect=fake), patch.object(controller.signal, 'signal') as signals:
            self.assertFalse(controller.cleanup_owned(CID)['State']['Running'])
            self.assertEqual([v[0][1] for v in calls], ['stop', 'kill', 'wait'])
            signals.assert_any_call(signal.SIGTERM, signal.SIG_IGN)

    def test_cleanup_rejects_still_running(self):
        with patch.object(controller, 'inspect_owned', return_value=state(True)), \
             patch.object(controller, 'run'), patch.object(controller.signal, 'signal'):
            with self.assertRaisesRegex(AssertionError, 'not terminal'):
                controller.cleanup_owned(CID)

    def test_cleanup_wrong_identity_cannot_stop_other_container(self):
        with patch.object(controller, 'inspect_owned', side_effect=AssertionError('ownership')), \
             patch.object(controller, 'run') as invoked, patch.object(controller.signal, 'signal'):
            with self.assertRaises(AssertionError):
                controller.cleanup_owned(CID)
            invoked.assert_not_called()

    def test_terminal_failure_is_preserved_without_stop(self):
        with patch.object(controller, 'inspect_owned', return_value=state()), \
             patch.object(controller, 'run') as invoked, patch.object(controller.signal, 'signal'):
            self.assertEqual(controller.cleanup_owned(CID)['State']['ExitCode'], 1)
            invoked.assert_not_called()

    def test_attached_cli_timeout_is_bounded_and_killed(self):
        attached = Mock()
        attached.wait.side_effect = [subprocess.TimeoutExpired('docker start', 15), 1]
        with patch.object(controller, 'inspect_owned', return_value=state()), \
             patch.object(controller.signal, 'signal'):
            controller.cleanup_owned(CID, attached)
        attached.kill.assert_called_once_with()
        self.assertEqual([c.kwargs['timeout'] for c in attached.wait.call_args_list], [15, 10])

    def test_limits_and_mounts_fail_closed(self):
        mounts = [(Path('/sdk'), '/build', False)]
        good = {'HostConfig': {'Memory': 4294967296, 'MemorySwap': 4294967296,
                'NanoCpus': 1000000000, 'NetworkMode': 'none', 'ReadonlyRootfs': True},
                'Mounts': [{'Type': 'bind', 'Destination': '/build', 'Source': '/sdk', 'RW': False}]}
        controller.validate_container(good, mounts)
        for field, bad in [('Memory', 8589934592), ('MemorySwap', -1), ('NanoCpus', 2000000000),
                           ('NetworkMode', 'default'), ('ReadonlyRootfs', False), ('Privileged', True),
                           ('Devices', ['/dev/dri/renderD128']), ('DeviceRequests', [{}])]:
            value = json.loads(json.dumps(good))
            value['HostConfig'][field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError):
                controller.validate_container(value, mounts)
        good['Mounts'][0]['RW'] = True
        with self.assertRaises(AssertionError):
            controller.validate_container(good, mounts)

    def test_low_memory_or_disk_prevents_preflight(self):
        budgets = {'minimum_free_disk_bytes': 6, 'minimum_host_available_memory_bytes': 6}
        for disk, memory in [(5, 7), (7, 5)]:
            with patch.object(controller.shutil, 'disk_usage', return_value=Mock(free=disk)), \
                 patch.object(controller, 'available_memory', return_value=memory), self.assertRaises(AssertionError):
                controller.host_reserves(Path('/unused'), budgets)

    def test_sdk_absolute_and_relative_symlinks_resolve_in_container_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            (sdk / 'usr/lib').mkdir(parents=True)
            (sdk / 'usr/lib/real.so').write_bytes(b'ELF fixture')
            (sdk / 'usr/lib/soname.so').symlink_to('real.so')
            (sdk / 'usr/lib/link.so').symlink_to('/build/usr/lib/soname.so')
            actual, destination = controller.original_file(sdk, '/build/usr/lib/link.so')
            self.assertEqual(actual, sdk / 'usr/lib/real.so')
            self.assertEqual(destination, '/build/usr/lib/real.so')

    def test_symlink_escape_and_loop_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            (sdk / 'escape').symlink_to('/etc/passwd')
            (sdk / 'loop').symlink_to('loop')
            with self.assertRaises(AssertionError):
                controller.original_file(sdk, '/build/escape')
            with self.assertRaises(RuntimeError):
                controller.original_file(sdk, '/build/loop')

    def test_resource_failure_not_claimed_final(self):
        with patch.object(controller, 'inspect_owned', side_effect=subprocess.TimeoutExpired('inspect', 15)):
            result = controller.sample_resources(CID)
        self.assertFalse(result['sampled'])
        self.assertFalse(result['final'])
        self.assertEqual(result['sample_error_type'], 'TimeoutExpired')

    def test_compiler_tmp_is_confined_and_counted(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / 'compiler-tmp').mkdir()
            (output / 'compiler-tmp/test.o').write_bytes(b'1234')
            with patch.object(controller.shutil, 'disk_usage', return_value=Mock(free=3 * 1024**3)):
                self.assertEqual(controller.compiler_tmp_usage(output), 4)

    def test_compiler_tmp_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / 'elsewhere').mkdir()
            (output / 'compiler-tmp').symlink_to(output / 'elsewhere', target_is_directory=True)
            with self.assertRaises(AssertionError):
                controller.compiler_tmp_usage(output)

    def test_compiler_tmp_budget_and_disk_reserve(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output / 'compiler-tmp').mkdir()
            (output / 'compiler-tmp/test.o').write_bytes(b'1234')
            with patch.object(controller, 'COMPILER_TMP_LIMIT', 3), self.assertRaises(AssertionError):
                controller.compiler_tmp_usage(output)
            with patch.object(controller.shutil, 'disk_usage', return_value=Mock(free=1024)), self.assertRaises(AssertionError):
                controller.compiler_tmp_usage(output)

    def test_compiler_tmp_completed_file_can_disappear_during_sample(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            temporary = output / 'compiler-tmp'
            temporary.mkdir()
            with patch.object(controller.os, 'walk', return_value=[(str(temporary), [], ['already-removed.o'])]), \
                 patch.object(controller.shutil, 'disk_usage', return_value=Mock(free=3 * 1024**3)):
                self.assertEqual(controller.compiler_tmp_usage(output), 0)


if __name__ == '__main__':
    unittest.main()
