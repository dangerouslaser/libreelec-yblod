"""Generated fixture/mock tests only; no systemd, media, network or GPU execution."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_vm_capture_comparisons as module


def comparison():
    return dict(schema='yblod.renderer-output-comparison.v1',
                identical_source_layer_timestamps=True, identical_source_metadata=True,
                output_preserved=True, differing_tunnel_rgb_bytes=0,
                picture_and_payload_preservation=dict(picture_and_payload_preserved=True),
                before=dict(native=1,native_planar=0,direct_packed=1),
                after=dict(native=1,native_planar=1,direct_packed=1),
                planes={key:dict(max_absolute_codes=0,exact_percent=100) for key in ('I','P','T')})


def stdout(report=None):
    return json.dumps(report or comparison())+'\nmemory.peak\n42864640\nmemory.events\nlow 0\nhigh 0\nmax 0\noom 0\noom_kill 0\nmemory.swap.current\n0\n'


class VMComparisons(unittest.TestCase):
    def test_exact_parse_and_resources(self):
        result, resources = module.parse_output(stdout())
        self.assertTrue(result['output_preserved'])
        self.assertEqual(resources['memory_peak_bytes'],42864640)

    def test_memory_failure_refused(self):
        for value in (stdout().replace('max 0','max 1'),stdout().replace('42864640','536870913'),stdout().replace('memory.swap.current\n0','memory.swap.current\n1'),stdout()+'unexpected'):
            with self.assertRaises(ValueError): module.parse_output(value)

    def test_picture_or_source_failure_refused(self):
        for key in ('identical_source_metadata','identical_source_layer_timestamps'):
            report=comparison();report[key]=False
            with self.assertRaises(ValueError): module.parse_output(stdout(report))
        report=comparison();report['planes']['I']['max_absolute_codes']=1
        with self.assertRaises(ValueError): module.parse_output(stdout(report))

    def test_no_leading_diagnostics_accepted_as_json(self):
        with self.assertRaises(ValueError): module.parse_output('diagnostic\n'+stdout())

    def fixture(self, root):
        stage=root/'yblod-test';stage.mkdir()
        captures=root/'captures';captures.mkdir()
        wrapper=stage/'run-vm-frame-comparison.sh';wrapper.touch()
        reports=[]
        for index in range(2):
            folder=captures/f'frame-{index}';folder.mkdir()
            frame=dict(directory=str(folder),width=3840,height=2160,pts=1201000000,
                       el_pts=1201000000,native=1,native_planar=index,direct_packed=1,qsv_mode=2)
            (folder/'frame.json').write_text(json.dumps({k:v for k,v in frame.items() if k!='directory'}))
            identity=dict(binary_sha256=('a' if index==0 else 'b')*64,pid=1,service_pid=2,start_ticks=3)
            report=dict(identity_before=identity,identity_after=identity.copy(),
                        shutdown='ActiveState=inactive\nResult=success\nMainPID=0',
                        movie=dict(id=3391,title='Saving Private Ryan',seek_seconds=1200),frames=[frame])
            path=stage/f'capture-{index}.json';path.write_text(json.dumps(report));reports.append(path)
        args=argparse.Namespace(before_report=str(reports[0]),after_report=str(reports[1]),
             before_binary_sha256='a'*64,after_binary_sha256='b'*64,
             expected_title='Saving Private Ryan',movie_id=3391,seek_seconds=1200,
             before_planar=0,after_planar=1,before_packed=1,after_packed=1,qsv_mode=2,
             expected_stage_root=str(stage),wrapper=str(wrapper),output=str(stage/'numeric-results'))
        return args,captures

    def test_complete_mock_run_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();args,captures=self.fixture(root)
            with patch.object(module,'CAPTURES',captures),patch.object(module,'STAGE_PARENT',root),patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout(),'')) as run,patch('builtins.print'):
                result=module.run(args)
            command=run.call_args.args[0]
            shell_index=command.index('sh')
            self.assertEqual(command[shell_index:shell_index+2],['sh',args.wrapper])
            for flag in ('--pipe','--wait','--collect','MemoryMax=512M','MemorySwapMax=0','CPUQuota=100%'):
                self.assertIn(flag,command)
            self.assertTrue(result['complete'])
            self.assertFalse(result['raw_media_exported'])
            self.assertFalse(result['private_media_hashes_exported'])
            self.assertNotIn(str(root),json.dumps(result))
            self.assertTrue((Path(args.output)/'comparison-00.json').is_file())

    def test_manifest_route_failure_before_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();args,captures=self.fixture(root)
            report=json.loads(Path(args.after_report).read_text());report['frames'][0]['native_planar']=0
            Path(args.after_report).write_text(json.dumps(report))
            with patch.object(module,'CAPTURES',captures),patch.object(module,'STAGE_PARENT',root),patch.object(module.subprocess,'run') as run:
                with self.assertRaises(ValueError):module.run(args)
                run.assert_not_called()
            self.assertFalse(Path(args.output).exists())

    def test_actual_frame_association_failure_before_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();args,captures=self.fixture(root)
            info=captures/'frame-1'/'frame.json';frame=json.loads(info.read_text());frame['pts']+=1;info.write_text(json.dumps(frame))
            with patch.object(module,'CAPTURES',captures),patch.object(module,'STAGE_PARENT',root),patch.object(module.subprocess,'run') as run:
                with self.assertRaises(ValueError):module.run(args)
                run.assert_not_called()


if __name__=='__main__':unittest.main()
