import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import argparse
import math

SOURCE = Path(__file__).with_name('capture_el_qsv_runtime_preservation.py')

class RollbackTests(unittest.TestCase):
    def run_case(self, pid, bound, removed, unexpected=False):
        prior=['lower','/yblod-renderer-step1-20261006/kodi-native-scheduling.bin']
        layers=prior[:] if not removed else prior[:-1]
        if bound:layers.append('/yblod-qsv-el-aff416-runtime/kodi-el-qsv-candidate.bin')
        if unexpected:layers[-1]='unrelated'
        calls=[]
        state={'pid':pid,'new':bound}
        def command(*args):
            calls.append(args)
            if args[:2]==('systemctl','show'):return str(state['pid'])
            if args[:2]==('systemctl','stop'):state['pid']=0
            if args[0]=='umount':layers.pop();state['new']=False
            if args[0]=='mount':layers.append(prior[-1]);state['new']=False
            if args[:2]==('systemctl','start'):state['pid']=42
            return ''
        override=SimpleNamespace(write_bytes=lambda b:None,read_bytes=lambda:b'original')
        capture=SimpleNamespace(command=command,rpc=lambda *a:[],
            process_identity=lambda:dict(binary_sha256='new' if state['new'] else 'old',pid=state['pid']))
        namespace=dict(capture=capture,OLD='old',NEW='new',OLD_MOUNT_ROOT=prior[-1],NEW_MOUNT_ROOT='/yblod-qsv-el-aff416-runtime/kodi-el-qsv-candidate.bin',TARGET=Path('/target'),OLD_SOURCE=Path('/old'),
            mounts=lambda:layers[:],sha=lambda p:'new' if state['new'] else 'old',
            mapped_family=lambda p:{'oldlib':'hash'},time=SimpleNamespace(sleep=lambda s:None))
        tree=ast.parse(SOURCE.read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='restore_owned')
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(SOURCE),'exec'),namespace)
        if unexpected:
            with self.assertRaises(RuntimeError):namespace['restore_owned'](prior,b'original',override,{'oldlib':'hash'},bound,removed,True)
            self.assertFalse(any(c[0]=='umount' for c in calls))
        else:
            result=namespace['restore_owned'](prior,b'original',override,{'oldlib':'hash'},bound,removed,True)
            self.assertTrue(all(result.values()))
            self.assertEqual(layers,prior)
        return calls

    def test_stop_failure_old_alive(self):
        calls=self.run_case(42,False,False)
        self.assertFalse(any(c[:2]==('systemctl','stop') or c[0]=='umount' for c in calls))
    def test_stop_failure_already_dead(self):self.run_case(0,False,False)
    def test_candidate_bind_failure(self):self.run_case(0,False,True)
    def test_capture_failure(self):self.run_case(42,True,True)
    def test_unexpected_top(self):self.run_case(0,True,True,True)
    def test_successful_restore(self):self.run_case(0,True,True)

class LauncherTests(unittest.TestCase):
    def helper(self):
        tree=ast.parse(SOURCE.read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='private_launcher_bytes')
        namespace={}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(SOURCE),'exec'),namespace)
        return namespace['private_launcher_bytes']
    def test_only_invocation_changed(self):
        old=b'#!/bin/sh\n. /etc/profile\n/usr/lib/kodi/kodi.bin $SAVED_ARGS\nexit $RET\n'
        new=self.helper()(old,Path('/storage/test/lib'))
        self.assertEqual(new,b'#!/bin/sh\n. /etc/profile\nLD_LIBRARY_PATH=/storage/test/lib:$LD_LIBRARY_PATH /usr/lib/kodi/kodi.bin $SAVED_ARGS\nexit $RET\n')
    def test_missing_or_duplicate_invocation_rejected(self):
        for value in (b'none',b'/usr/lib/kodi/kodi.bin $SAVED_ARGS\n'*2):
            with self.assertRaises(ValueError):self.helper()(value,Path('/storage/test/lib'))

class ParsingTests(unittest.TestCase):
    def helpers(self):
        tree=ast.parse(SOURCE.read_text())
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('positive_movie_id','positive_seek')]
        namespace={'argparse':argparse,'math':math}
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(SOURCE),'exec'),namespace)
        return namespace
    def test_positive_movie_id(self):
        parse=self.helpers()['positive_movie_id']
        self.assertEqual(parse('51'),51)
        for value in ('0','-1','1.5','nan','bad'):
            with self.assertRaises(argparse.ArgumentTypeError):parse(value)
    def test_finite_positive_seek(self):
        parse=self.helpers()['positive_seek']
        self.assertEqual(parse('1200.5'),1200.5)
        for value in ('0','-1','nan','inf','-inf','bad'):
            with self.assertRaises(argparse.ArgumentTypeError):parse(value)

if __name__=='__main__':unittest.main()
