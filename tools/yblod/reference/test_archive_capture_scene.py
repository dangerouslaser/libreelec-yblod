import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import archive_capture_scene as module


def report():
    identity = dict(binary_sha256='a'*64, pid=1, service_pid=2, start_ticks=3)
    return dict(identity_before=identity, identity_after=identity.copy(),
                shutdown='ActiveState=inactive\nResult=success\nMainPID=0\n',
                movie=dict(id=3391, title='Saving Private Ryan', seek_seconds=1200),
                frames=[dict(directory='/storage/dvbridge-output-captures/frame-123-456',
                             width=3840, height=2160, pts=1201000000, native=1,
                             native_planar=1, direct_packed=1, qsv_mode=2)])


class ArchiveTests(unittest.TestCase):
    def test_unexpected_report_root_rejected_before_network(self):
        args = argparse.Namespace(vm_report='/storage/other/report.json', expected_report_root='/storage')
        with patch.object(module, 'remote') as remote, self.assertRaises(ValueError):
            module.archive(args)
        remote.assert_not_called()

    def test_report_identity_guards(self):
        value = report()
        self.assertEqual(len(module.validate_report(value, 'a'*64, 3391, 'Saving Private Ryan')), 1)
        for mutation in ('identity', 'movie', 'shutdown', 'directory', 'duplicate', 'dimensions', 'bool_pid', 'zero_ticks'):
            changed = copy.deepcopy(value)
            if mutation == 'identity': changed['identity_after']['pid'] += 1
            if mutation == 'movie': changed['movie']['title'] = '1917'
            if mutation == 'shutdown': changed['shutdown'] = 'ActiveState=active'
            if mutation == 'directory': changed['frames'][0]['directory'] += '/../escape'
            if mutation == 'duplicate': changed['frames'] *= 2
            if mutation == 'dimensions': changed['frames'][0]['width'] = 1
            if mutation == 'bool_pid': changed['identity_before']['pid'] = changed['identity_after']['pid'] = True
            if mutation == 'zero_ticks': changed['identity_before']['start_ticks'] = changed['identity_after']['start_ticks'] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                module.validate_report(changed, 'a'*64, 3391, 'Saving Private Ryan')

    def test_file_report_identity(self):
        value=report()
        del value['movie']
        value['file']=dict(basename='DV FEL All Layers Test (Woman at 80s).mkv',seek_seconds=80)
        self.assertEqual(len(module.validate_report(value,'a'*64,file_basename=value['file']['basename'])),1)
        for filename in ('different.mkv','../escape.mkv',''):
            with self.subTest(filename=filename),self.assertRaises(ValueError):
                module.validate_report(value,'a'*64,file_basename=filename)
        with self.assertRaises(ValueError): module.validate_report(value,'a'*64,3391,'Saving Private Ryan',value['file']['basename'])

    def test_chunked_hash_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'payload'
            source.write_bytes(b'a'*(1024*1024+17))
            self.assertEqual(module.local_hash(source)['size'], 1024*1024+17)
            (root/'link').symlink_to(source)
            with self.assertRaises(ValueError): module.local_hash(root/'link')

    def test_remote_request_and_metadata_size_guards_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            for name in module.FILES: (root/name).write_bytes(b'x')
            for name,size in (('request',0),('request',257),('metadata.bin',0),('metadata.bin',1048577)):
                for item in ('request','metadata.bin'): (root/item).write_bytes(b'x')
                with (root/name).open('r+b') as output: output.truncate(size)
                result=subprocess.run([sys.executable,'-c',module.REMOTE_HASH,str(root)],capture_output=True)
                with self.subTest(name=name,size=size): self.assertNotEqual(result.returncode,0)

    def test_archiving_three_way_exact_without_network(self):
        value = report()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            vm = root/'vm'; vm.mkdir()
            ollie = root/'ollie'
            local = root/'local'
            frame = value['frames'][0]
            name = Path(frame['directory']).name
            source = vm/name; source.mkdir()
            (source/'request').write_text('1201000000 1\n')
            (source/'metadata.bin').write_bytes(b'metadata')
            (source/'output.rgba').touch()
            # Sparse generated fixture; never media.
            with (source/'output.rgba').open('r+b') as output: output.truncate(3840*2160*4)
            (source/'frame.json').write_text(json.dumps({k:v for k,v in frame.items() if k!='directory'}))
            args = argparse.Namespace(vm_host='vm', vm_report='/storage/capture.json',
                                     expected_report_root='/storage', binary_sha256='a'*64,
                                     movie_id=3391, expected_title='Saving Private Ryan',
                                     expected_file_basename=None,
                                     local_archive=str(local), ollie_host='ollie', ollie_archive=str(ollie))
            def remote(host, *arguments):
                if 'print(p.read_text())' in arguments[2]: return json.dumps(value)
                Path(arguments[-1]).mkdir()
                return ''
            def remote_hash(host, directory):
                target = vm/Path(str(directory)).name if host=='vm' else Path(str(directory))
                return {n:module.local_hash(target/n) for n in module.FILES}
            def command(*arguments):
                second=arguments[-1]
                destination = Path(second.split(':',1)[1]) if second.startswith('ollie:') else Path(second)
                self.assertEqual(len(arguments[4:-1]),4)
                for first in arguments[4:-1]:
                    source_path = vm/name/first.rsplit('/',1)[1] if first.startswith('vm:') else Path(first)
                    shutil.copyfile(source_path, destination/source_path.name)
                return ''
            with patch.object(module, 'remote', remote), patch.object(module, 'remote_hash', remote_hash), patch.object(module, 'command', command), patch('builtins.print'):
                result = module.archive(args)
            self.assertTrue(result['complete'])
            self.assertFalse(result['vm_files_deleted'])
            self.assertEqual(set(result['frames'][0]['files']), set(module.FILES))
            self.assertTrue((source/'output.rgba').exists())
            self.assertEqual(json.loads((local/'archive-verification.json').read_text()), result)
            args.local_archive=str(root/'bad-local')
            args.ollie_archive=str(root/'bad-ollie')
            def mismatched_hash(host, directory):
                result=remote_hash(host,directory)
                if host=='ollie': result['metadata.bin']['sha256']='b'*64
                return result
            with patch.object(module, 'remote', remote), patch.object(module, 'remote_hash', mismatched_hash), patch.object(module, 'command', command), patch('builtins.print'), self.assertRaises(ValueError):
                module.archive(args)
            self.assertFalse((root/'bad-local'/'archive-verification.json').exists())
            self.assertTrue((source/'output.rgba').exists())


if __name__ == '__main__': unittest.main()
