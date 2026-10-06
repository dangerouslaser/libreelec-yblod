"""Generated capture and subprocess mocks only; no VM, media or GPU operations."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_native_optimization_frame_comparisons as module
from native_optimization_qualification import qualify_frames


def fixture(root, option='batched_planes', legacy=False):
    stage=root/'yblod-test';stage.mkdir()
    captures=root/'captures';captures.mkdir()
    wrapper=stage/'wrapper.sh';wrapper.touch()
    reports=[]
    for enabled in (0, 1):
        frames=[]
        for index in range(3):
            folder=captures/f'frame-{enabled}-{index}';folder.mkdir()
            frame=dict(directory=str(folder), width=3840, height=2160,
                pts=1210000000+index*10000000, el_pts=1210000000+index*10000000,
                native=1, direct_packed=1, native_planar=1, qsv_mode=1,
                batched_planes=0, immutable_instructions=0, private_media_hash='PRIVATE-MEDIA-HASH')
            if not legacy:
                frame[option]=enabled
            elif not enabled:
                for key in module.OPTIONS:frame.pop(key)
            (folder/'frame.json').write_text(json.dumps({k:v for k,v in frame.items() if k!='directory'}))
            frames.append(frame)
        identity=dict(binary_sha256='a'*64 if legacy and not enabled else '0'*64,pid=1,service_pid=2,start_ticks=3)
        original=dict(enabled=True,index=0);disabled=dict(enabled=False,index=0)
        report=dict(identity_before=identity,identity_after=identity.copy(),
            shutdown='ActiveState=inactive\nResult=success\nMainPID=0',
            movie=dict(id=3391,title='Saving Private Ryan',seek_seconds=1200),frames=frames,
            subtitle_fixture=dict(movie_id=3391,player_id=1,requested_enabled=False,
                before=original,disabled=disabled,disabled_at_end=disabled.copy(),restored=original.copy()))
        path=stage/f'capture-{enabled}.json';path.write_text(json.dumps(report));reports.append(path)
    args=argparse.Namespace(before_report=str(reports[0]),after_report=str(reports[1]),
        binary_sha256='0'*64,optimization=None if legacy else option,
        baseline_binary_sha256='a'*64 if legacy else None,
        expected_stage_root=str(stage),wrapper=str(wrapper),output=str(stage/'results'))
    return args,captures


def output(option='batched_planes', legacy=False):
    routes=[]
    for enabled in (0,1):
        route=dict(native=1,direct_packed=1,native_planar=1,batched_planes=0,immutable_instructions=0)
        if not legacy:route[option]=enabled
        elif not enabled:
            for key in module.OPTIONS:route.pop(key)
        routes.append(route)
    comparison=dict(schema='yblod.renderer-output-comparison.v1',
        identical_source_layer_timestamps=True,identical_source_metadata=True,
        picture_and_payload_preservation=dict(picture_and_payload_preserved=True),
        before=routes[0],after=routes[1],metadata_hash='PRIVATE-MEDIA-HASH',private_path='/private-do-not-publish',
        planes={key:dict(max_absolute_codes=0,exact_percent=100) for key in ('I','P','T')})
    return json.dumps(comparison)+'\nmemory.peak\n42864640\nmemory.events\nlow 0\nhigh 0\nmax 0\noom 0\noom_kill 0\nmemory.swap.current\n0\n'


class Tests(unittest.TestCase):
    def run_mock(self, args, captures, stdout):
        with patch.object(module.base,'CAPTURES',captures),patch.object(module.base,'STAGE_PARENT',captures.parent), \
             patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout,'')) as run,patch('builtins.print'):
            return module.run(args),run

    def test_both_options_public_schema_qualifier_resources_and_privacy(self):
        for option in module.OPTIONS:
            with tempfile.TemporaryDirectory() as temporary:
                args,captures=fixture(Path(temporary).resolve(),option)
                result,run=self.run_mock(args,captures,output(option))
                self.assertEqual(run.call_count,3)
                qualify_frames(Path(args.output)/'comparison-summary.json','0'*64,option)
                text=json.dumps(result)
                for private in ('PRIVATE-MEDIA-HASH','/private-do-not-publish',temporary):self.assertNotIn(private,text)
                for command in run.call_args_list:
                    self.assertIn('MemoryMax=512M',command.args[0])
                    self.assertIn('MemorySwapMax=0',command.args[0])
                    self.assertIn('CPUQuota=100%',command.args[0])
                self.assertEqual(result['frames'][0]['resources']['memory_peak_bytes'],42864640)

    def test_retained_baseline_missing_fields_not_inferred(self):
        with tempfile.TemporaryDirectory() as temporary:
            args,captures=fixture(Path(temporary).resolve(),legacy=True)
            result,_=self.run_mock(args,captures,output(legacy=True))
            self.assertEqual(result['schema'],'yblod.native-optimization-baseline-preservation-results.v1')
            self.assertNotIn('batched_planes',result['frames'][0]['before']['route'])
            self.assertEqual(result['frames'][0]['after']['route']['batched_planes'],0)

    def test_report_source_route_fixture_binary_and_three_frame_guards_precede_comparator(self):
        for edit in (
            lambda r:r['identity_after'].update(start_ticks=4),
            lambda r:r['identity_before'].update(binary_sha256='1'*64),
            lambda r:r['subtitle_fixture']['restored'].update(enabled=False),
            lambda r:r['frames'][0].update(batched_planes=True),
            lambda r:r['frames'][0].update(immutable_instructions=1),
            lambda r:r['frames'][0].update(qsv_mode=2),
            lambda r:r['frames'][0].update(pts=1210000000.5),
            lambda r:r['frames'].pop(),
            lambda r:r.update(shutdown='ActiveState=active'),
        ):
            with tempfile.TemporaryDirectory() as temporary:
                args,captures=fixture(Path(temporary).resolve())
                report=json.loads(Path(args.after_report).read_text());edit(report)
                Path(args.after_report).write_text(json.dumps(report))
                with patch.object(module.base,'CAPTURES',captures),patch.object(module.base,'STAGE_PARENT',captures.parent),patch.object(module.subprocess,'run') as run:
                    with self.assertRaises(ValueError):module.run(args)
                    run.assert_not_called()
                self.assertFalse(Path(args.output).exists())

    def test_frame_file_association_and_pair_timestamps_refused_before_comparison(self):
        for mismatch in ('manifest','paired'):
            with tempfile.TemporaryDirectory() as temporary:
                args,captures=fixture(Path(temporary).resolve())
                frame_path=captures/'frame-1-0'/'frame.json'
                frame=json.loads(frame_path.read_text());frame['pts']+=100;frame['el_pts']+=100
                frame_path.write_text(json.dumps(frame))
                if mismatch=='paired':
                    report=json.loads(Path(args.after_report).read_text())
                    report['frames'][0].update(pts=frame['pts'],el_pts=frame['el_pts'])
                    Path(args.after_report).write_text(json.dumps(report))
                with patch.object(module.base,'CAPTURES',captures),patch.object(module.base,'STAGE_PARENT',captures.parent),patch.object(module.subprocess,'run') as run:
                    with self.assertRaises(ValueError):module.run(args)
                    run.assert_not_called()

    def test_comparator_typed_flags_exact_planes_source_payload_and_resource_failure_refused(self):
        stdout=output()
        for changed in (
            stdout.replace('"batched_planes": 1','"batched_planes": true'),
            stdout.replace('"max_absolute_codes": 0','"max_absolute_codes": false'),
            stdout.replace('"exact_percent": 100','"exact_percent": 99.9'),
            stdout.replace('"identical_source_metadata": true','"identical_source_metadata": 1'),
            stdout.replace('"picture_and_payload_preserved": true','"picture_and_payload_preserved": 1'),
            stdout.replace('max 0','max 1'),
            stdout.replace('42864640','536870913'),
            stdout+'unexpected',
        ):
            with tempfile.TemporaryDirectory() as temporary:
                args,captures=fixture(Path(temporary).resolve())
                with self.assertRaises(ValueError):self.run_mock(args,captures,changed)


if __name__=='__main__':unittest.main()
