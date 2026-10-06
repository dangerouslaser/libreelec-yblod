import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import package_el_qsv_runtime as packaging
from package_el_qsv_runtime import resolve
from collect_el_qsv_target_identity import fingerprint, qualify
import run_target_el_qsv_probe as launcher


class RuntimeTools(unittest.TestCase):
    def test_live_checkpoint_matches_unit_and_ack_exact_nonce(self):
        with tempfile.TemporaryDirectory() as temp:
            ready, ack = Path(temp) / 'ready', Path(temp) / 'ack'
            nonce = 'a'*64
            launcher.handshake_environment(ready, ack, nonce)
            ready.write_text(json.dumps(dict(pid=42, nonce=nonce)))
            os.chmod(ready, 0o600)
            with self.assertRaises(ValueError):
                launcher.acknowledge_live_probe(ready, ack, nonce, 43, 'node', {}, 'driver')
            self.assertFalse(ack.exists())
            with patch.object(launcher, 'process_gpu_client', return_value=[{'drm-client-id':'1'}]), patch.object(launcher, 'mapped_libraries', return_value=True):
                launcher.acknowledge_live_probe(ready, ack, nonce, 42, 'node', {}, 'driver')
            self.assertEqual(ack.read_bytes(), nonce.encode())
            self.assertEqual(ack.stat().st_mode & 0o777, 0o600)

    def test_launch_preflight_refuses_user_playback(self):
        with patch.object(launcher, 'rpc', return_value=[{'playerid':1}]):
            with self.assertRaises(ValueError): launcher.idle_movie_source()

    def test_core_dependencies_remain_target_owned_and_versions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            libs = root / 'x86_64-libreelec-linux-gnu/sysroot/usr/lib'
            libs.mkdir(parents=True)
            (libs / 'libavcodec.so.63.1.102').write_bytes(b'fixture')
            (libs / 'libavcodec.so').symlink_to('libavcodec.so.63.1.102')
            target = dict(actual_target_identity_verified=True, existing_driver_identity_verified=True,
                libraries={'libc.so.6':dict(elf64_x86_64=True, actual_resolution_verified=True,
                    sha256='a'*64, defined_versions=['GLIBC_2.44'])})
            info = (['libc.so.6'], 'libavcodec.so.63', {'libc.so.6':['GLIBC_2.44']})
            with patch.object(packaging, 'ROOTS', ('libavcodec.so',)), patch.object(packaging, 'elf', return_value=info):
                aliases, files, external = packaging.plan(root, Path('/build/sdk'), 'readelf', target)
                self.assertEqual(set(files), {'libavcodec.so.63.1.102'})
                self.assertEqual(set(external), {'libc.so.6'})
                target['libraries']['libc.so.6']['defined_versions'] = ['GLIBC_2.38']
                with self.assertRaises(ValueError): packaging.plan(root, Path('/build/sdk'), 'readelf', target)

    def test_absolute_sdk_link_remaps_without_host_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'lib.so.2').write_bytes(b'fixture')
            (root / 'lib.so').symlink_to('/build/sdk/lib.so.2')
            self.assertEqual(resolve(root / 'lib.so', root, Path('/build/sdk')), root / 'lib.so.2')
            (root / 'bad.so').symlink_to('/usr/lib/lib.so')
            with self.assertRaises(ValueError): resolve(root / 'bad.so', root, Path('/build/sdk'))

    def test_fingerprint_regular_content(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'private'
            file.write_bytes(b'fixture')
            before = fingerprint(file)
            file.write_bytes(b'changed')
            self.assertNotEqual(before, fingerprint(file))

    def test_target_identity_requires_all_actual_evidence(self):
        before = dict(host='private-host', gpu=dict(device='private-device'),
            input=('private-file', 'private-content'), binary=('stat', 'binary'),
            runtime={'lib':('stat', 'library')}, driver=('stat', 'driver'))
        args = [before, copy.deepcopy(before), dict(host=before['host'], gpu=before['gpu']),
                'binary', {'lib':'library'}, 'driver', [{'drm-client-id':'1'}], True, True]
        self.assertTrue(all(qualify(*args).values()))
        for index, value in ((3,'wrong'), (5,'changed'), (6,[]), (7,1), (8,1)):
            changed = copy.deepcopy(args)
            changed[index] = value
            with self.assertRaises(ValueError): qualify(*changed)
        changed = copy.deepcopy(args)
        changed[1]['input'] = ('private-file','changed')
        with self.assertRaises(ValueError): qualify(*changed)


if __name__ == '__main__': unittest.main()
