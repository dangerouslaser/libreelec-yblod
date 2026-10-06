import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_native_planar_long_matrix as module
from test_native_planar_matrix import planar_report


def proof(movie_id=3391):
    name = 'NATIVE_PLANAR_SPR_FRAME_RESULTS.json' if movie_id==3391 else 'NATIVE_PLANAR_1917_FRAME_RESULTS.json'
    value=json.loads(Path(__file__).with_name(name).read_text())
    value['candidate_binary_sha256']='0'*64
    return value


def fixture(movie_id=3391,enabled=True):
    before=dict(enabled=enabled,index=0)
    disabled=dict(enabled=False,index=0)
    return dict(movie_id=movie_id,player_id=1,before=before,requested_enabled=False,
                disabled=disabled,disabled_at_end=disabled.copy(),restored=before.copy())


class Tests(unittest.TestCase):
    def make_args(self, root, movie_id=3391):
        output=root/'output';output.mkdir()
        record=root/'proof.json';record.write_text(json.dumps(proof(movie_id)))
        return module.argument_parser().parse_args(['--binary-sha256','0'*64,'--root',str(output),
            '--observer',str(Path(__file__).with_name('observe_native_movie.py')),
            '--config-dir',str(Path(__file__).parent),'--movie-id',str(movie_id),
            '--expected-title',module.MOVIES[movie_id][0],'--subtitles-off','--preservation-report',str(record)])

    def test_actual_public_schema_for_both_movies(self):
        for movie in (3391,51):
            with tempfile.TemporaryDirectory() as temporary:
                args=self.make_args(Path(temporary),movie)
                self.assertEqual((args.seconds,args.seek_seconds),(600,1200))
                result=module.validate_long_planar_args(args)
                self.assertEqual(result[0]['frame_count'],3)
                self.assertEqual(result[0]['movie_id'],movie)

    def test_fixed_duration_scene_identity_subtitles_and_proof_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=self.make_args(Path(temporary))
            for key,value in (('seconds',180),('seconds',599),('seconds',601),('seek_seconds',0),
                              ('movie_id',999),('expected_title','1917'),('subtitles_off',False),('preservation_report',[])):
                changed=copy.copy(args);setattr(changed,key,value)
                with self.subTest(key=key,value=value),self.assertRaises(ValueError): module.validate_long_planar_args(changed)

    def test_wrong_binary_movie_schema_or_scene_proof_rejected(self):
        edits=(lambda v:v.update(candidate_binary_sha256='1'*64),
               lambda v:v.update(content='1917'),lambda v:v.update(schema='unknown'),
               lambda v:v.update(seek_seconds=1199),
               lambda v:v.update(comparisons=[v['comparisons'][0]]),
               lambda v:v['comparisons'].append(copy.deepcopy(v['comparisons'][1])))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'proof.json'
            for edit in edits:
                value=proof();edit(value);path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): module.sustained_planar_preservation_report(path,'0'*64,3391,'Saving Private Ryan')

    def test_every_selected_frame_source_route_precision_and_timestamps_checked(self):
        edits=(lambda rows:rows.pop(),
               lambda rows:rows[-1].update(source_metadata_equal=False),
               lambda rows:rows[-1].update(source_timestamps_equal=1),
               lambda rows:rows[-1].update(picture_and_payload_preserved=False),
               lambda rows:rows[-1]['after']['route'].update(native_planar=0),
               lambda rows:rows[-1]['before']['route'].update(direct_packed=0),
               lambda rows:rows[-1]['after']['route'].update(native=True),
               lambda rows:rows[-1]['after']['route'].update(qsv_mode=2),
               lambda rows:rows[-1]['maximum_absolute_12bit_codes'].update(I=1),
               lambda rows:rows[-1]['maximum_absolute_12bit_codes'].update(P=False),
               lambda rows:rows[-1]['exact_picture_percent'].update(T=99.9),
               lambda rows:rows[-1]['after'].update(el_pts_microseconds=1),
               lambda rows:rows[-1].update(frame_label=rows[0]['frame_label']),
               lambda rows:rows.reverse())
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'proof.json'
            for edit in edits:
                value=proof();edit(value['comparisons'][1]['frames']);path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): module.sustained_planar_preservation_report(path,'0'*64,3391,'Saving Private Ryan')

    def test_only_planar_flag_may_differ_and_captures_remain_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);args=self.make_args(root);args.config_dir=root
            originals=[Path(__file__).with_name(f'native-planar-{flag}.conf').read_text() for flag in (0,1)]
            for extra in ('Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT=0\n',
                          'Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT=0\n',
                          'Environment=DVBRIDGE_CAPTURE_OUTPUTS=1\n',
                          'Environment=UNRELATED=1\n'):
                for flag in (0,1):(root/f'native-planar-{flag}.conf').write_text(originals[flag]+(extra if flag else ''))
                with self.assertRaises(ValueError): module.validate_long_planar_args(args)

    def test_runtime_routes_and_restored_original_subtitle_state_remain_matched(self):
        validate=module.make_long_planar_validator(3391)
        for flag in (0,1,1,0):
            report,stopped=planar_report(flag);report['subtitle_fixture']=fixture()
            result=validate(report,stopped,flag,'0'*64)
            self.assertEqual(result['packed_output']['packed_preparation_percent'],100)
            self.assertEqual(result['native_planar']['planar_preparation_percent'],100*flag)
        report,stopped=planar_report(0);report['subtitle_fixture']=fixture(enabled=False)
        with self.assertRaises(ValueError): validate(report,stopped,0,'0'*64)

    def test_missing_wrong_or_malformed_subtitle_fixture_rejected(self):
        for edit in (lambda r:None,lambda r:r.update(subtitle_fixture=fixture(51)),
                     lambda r:r.update(subtitle_fixture=fixture()),):
            report,stopped=planar_report(0);edit(report)
            if 'subtitle_fixture' in report and report['subtitle_fixture']['movie_id']==3391:
                report['subtitle_fixture']['restored']['enabled']=0
            with self.assertRaises(ValueError): module.make_long_planar_validator(3391)(report,stopped,0,'0'*64)

    def test_main_labels_and_shared_lifecycle_with_no_playback(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=self.make_args(Path(temporary),51)
            with patch.object(module,'argument_parser') as parser,patch.object(module,'run_configured_matrix') as run,patch('builtins.print'):
                parser.return_value.parse_args.return_value=args
                module.main()
            passed=run.call_args.args
            self.assertEqual(passed[2],'native-planar-long-movie51')
            self.assertEqual([p.name for p in passed[1]],['native-planar-0.conf','native-planar-1.conf'])


if __name__=='__main__': unittest.main()
