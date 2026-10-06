import contextlib
import io
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import observe_live_el_qsv_probe as observer

PTS=[1210000000,1220010000,1230020000]

class FakeChild:
    pid=42
    def __init__(self,forever=False):self.returncode=None;self.forever=forever;self.polls=0;self.terminated=False;self.killed=False
    def poll(self):
        self.polls+=1
        if not self.forever and self.polls>1:self.returncode=0
        return self.returncode
    def terminate(self):self.terminated=True;self.returncode=-15
    def kill(self):self.killed=True;self.returncode=-9
    def wait(self,timeout=None):return self.returncode

class ObserverTests(unittest.TestCase):
    def run_case(self,mode='success'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runtime=root/'lib';runtime.mkdir()
            for name in ('loader','binary','driver','source'):(root/name).write_bytes(b'fixture')
            for name in ('libvpl.so.2.17','libmfx-gen.so.1.2.17'):(runtime/name).write_bytes(b'fixture')
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'files':{'loader':{'path':str(root/'loader'),'sha256':'c'*64}}}))
            argv=['observer','--binary',str(root/'binary'),'--loader',str(root/'loader'),'--runtime',str(runtime),
                '--driver',str(root/'driver'),'--source',str(root/'source'),'--node',str(root/'node'),
                '--runtime-identity',str(manifest),'--private-prefix',str(root/'result'),
                '--expected-code-root',str(root),
                '--binary-sha256','a'*64,'--driver-sha256','b'*64,'--seek-us','1200000000']
            for pts in PTS:argv+=['--pts-us',str(pts)]
            (root/'node').write_bytes(b'node')
            identity=dict(gpu='private-device',input='private-stat',binary=('stat','a'*64),driver=('stat','b'*64),runtime={'loader':('stat','c'*64)})
            child=FakeChild(mode=='deadline')
            def launch(command,env,stdout,stderr):
                Path(env['YB_QSV_PROBE_READY']).write_text(json.dumps({'pid':42,'nonce':env['YB_QSV_PROBE_NONCE']}))
                Path(env['YB_QSV_PROBE_READY']).chmod(0o600)
                frames=[dict(requested_pts_microseconds=p,before={'pts_microseconds':p},after={'pts_microseconds':p}) for p in PTS]
                if mode=='wrong-pts':frames[1]['after']['pts_microseconds']+=1
                stdout.write(json.dumps(dict(pass_=True)).encode() if mode=='probe-report' else json.dumps({'pass':True,'qsv_mapped_frames':3,'frames':frames}).encode());stdout.flush()
                return child
            resources=dict(memory_limit_bytes=536870912,swap_limit_bytes=0,cpu_limit=1,
                peak_memory_bytes=1024,memory_events={'oom':0},swap_current_bytes=0,swap_peak_bytes=0)
            final=dict(resources)
            if mode=='resource':final['peak_memory_bytes']=0
            observations=[identity,dict(identity,input='changed') if mode=='identity' else identity]
            clock=iter([0,0,171,180]) if mode=='deadline' else None
            output=io.StringIO()
            def acknowledge(*args,**kwargs):
                if mode=='audit-closure':
                    kwargs['private_library_audit'].write_text(json.dumps({'mapped_code':[{'path':'private-unknown.so'}],'summary':{'canonical_so_count':24,'under_expected_code_root_count':24,'outside_expected_code_root_count':0,'deleted_map_count':0}}))
                if mode in ('callback-closure','audit-closure'):raise ValueError('Mapped library outside the exact isolated closure/current driver')
                return {'probe_pid':42}
            with patch('sys.argv',argv),patch.object(observer,'resources',side_effect=[resources,final]),patch.object(observer,'observe',side_effect=observations),patch.object(observer,'process_record',return_value={'pid':1,'start_ticks':9}),patch.object(observer,'acknowledge_unit_child',side_effect=acknowledge),patch.object(observer.subprocess,'Popen',side_effect=launch),patch.object(observer.signal,'signal'),patch.object(observer.time,'sleep'),patch.object(observer.time,'monotonic',side_effect=(lambda:next(clock)) if clock else None,return_value=1),contextlib.redirect_stdout(output):
                code=observer.main()
            result=json.loads(output.getvalue())
            self.assertEqual(result['pass'],mode=='success')
            self.assertEqual(code,0 if mode=='success' else 1)
            if mode=='deadline':self.assertTrue(child.terminated);self.assertFalse(child.killed)
            if mode=='callback-closure':
                self.assertEqual(result['failure_stage'],'live_identity_callback')
                self.assertEqual(result['failure_code'],'mapped_library_closure')
            if mode=='audit-closure':
                self.assertEqual(result['mapped_code_audit_summary']['canonical_so_count'],24)
                self.assertNotIn('private-unknown',output.getvalue())
                self.assertNotIn('mapped_code',result)
    def test_success(self):self.run_case()
    def test_identity_failure(self):self.run_case('identity')
    def test_probe_report_failure(self):self.run_case('probe-report')
    def test_deadline_owned_child_termination(self):self.run_case('deadline')
    def test_resource_failure(self):self.run_case('resource')
    def test_literal_timestamp_failure(self):self.run_case('wrong-pts')
    def test_callback_failure_exports_only_static_stage_code(self):self.run_case('callback-closure')
    def test_private_audit_summary_only_exported_on_failure(self):self.run_case('audit-closure')
    def test_code_fingerprint_advises_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'code';value=b'x'*1048576+b'tail';file.write_bytes(value)
            with patch.object(observer.os,'posix_fadvise',create=True) as advise,patch.object(observer.os,'POSIX_FADV_DONTNEED',4,create=True),patch.object(observer.os,'sysconf',return_value=4096):
                identity,digest=observer.code_fingerprint(file)
            self.assertEqual(digest,hashlib.sha256(value).hexdigest())
            self.assertEqual(file.read_bytes(),value)
            self.assertEqual(advise.call_count,1)
            self.assertEqual(advise.call_args_list[0].args[1:3],(0,1048576))
    def test_code_cache_advice_failure_is_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'code';file.write_bytes(b'x'*1048576)
            with patch.object(observer.os,'posix_fadvise',side_effect=OSError('not available'),create=True),patch.object(observer.os,'POSIX_FADV_DONTNEED',4,create=True),patch.object(observer.os,'sysconf',return_value=4096):
                with self.assertRaises(OSError):observer.code_fingerprint(file)
    def test_failure_code_whitelist_never_exports_private_values(self):
        self.assertEqual(observer.SAFE_FAILURE_CODES['Actual loader/probe invocation differs'],'loader_or_argv')
        for private in ('/private/movie','argv=private','nonce=private'):
            self.assertNotIn(private,observer.SAFE_FAILURE_CODES)

if __name__=='__main__':unittest.main()
