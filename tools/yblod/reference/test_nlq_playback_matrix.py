import copy
import tempfile
import unittest
from pathlib import Path
from run_nlq_playback_matrix import lut_summary,parser,validate_lut_args


def line(flag,accepted=360,**changes):
    values=dict(nlq_lut_enabled=flag,accepted_lut=accepted if flag else 0,
        fp32_selected=1,accepted_fp32=accepted,accepted_integer=0,
        nlq_builds=1 if flag else 0,nlq_uploads=1 if flag else 0,
        nlq_cache_hits=accepted-1 if flag else 0,nlq_shader_compiles=flag,
        shader_compile_failed=0,generate_failed=0)
    values.update(changes)
    return 'DVBridge native composer: '+' '.join(f'{k}={v}' for k,v in values.items())


class Tests(unittest.TestCase):
    def test_modes(self):
        for flag in (0,1):
            self.assertEqual(lut_summary([line(flag,120),line(flag)],flag)['requested_flag'],flag)

    def test_fail_closed(self):
        for rows,flag in (([],1),([line(0,120),line(0)],1),
            ([line(1,120),line(1,accepted_integer=1)],1),
            ([line(1,120),line(1,nlq_uploads=2)],1),
            ([line(1,120),line(1,shader_compile_failed=1)],1),
            ([line(0,120),line(0,nlq_builds=1,nlq_uploads=1)],0),
            ([line(1,120),line(1,accepted_lut=359)],1),
            ([line(1,360),line(1,240)],1),([line(1)],1)):
            with self.assertRaises(ValueError):lut_summary(rows,flag)

    def test_incomplete(self):
        with self.assertRaises(ValueError):lut_summary(['DVBridge native composer: nlq_lut_enabled=1'],1)

    def test_bounds_and_exact_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);observer=p/'observer.py';observer.touch();out=p/'out';out.mkdir()
            args=parser().parse_args(['--binary-sha256','a'*64,'--root',str(out),
                '--observer',str(observer),'--config-dir',str(Path(__file__).parent),
                '--movie-id','51','--expected-title','1917','--seconds','180'])
            validate_lut_args(args)
            bad=copy.copy(args);bad.seconds=75
            with self.assertRaises(ValueError):validate_lut_args(bad)


if __name__=='__main__':unittest.main()
