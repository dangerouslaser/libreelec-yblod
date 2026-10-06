"""Matched SPR180 EL API ABBA, admitted by additive canonical frame proof."""
import json
from pathlib import Path
from el_qsv_canonical_qualification import qualify_report
from run_el_qsv_matrix import config_paths,validate_configs,make_validator
from run_colour_import_matrix import parser,run_configured_matrix,validate_request


def validate_args(args):
    validate_request(args)
    if (args.seconds!=180 or args.movie_id!=3391 or args.expected_title!='Saving Private Ryan' or
            args.seek_seconds!=1200 or args.subtitles_off is not True or args.planar_flag!=1 or
            args.observer.name!='observe_el_qsv_active_movie.py'):
        raise ValueError('Same SPR180 subtitle-free EL-only planar1 scene required')
    validate_configs(config_paths(args),1)
    return qualify_report(args.qualification_report,args.binary_sha256,args.qualification_sha256)


def main():
    p=parser();p.set_defaults(seconds=180,seek_seconds=1200)
    p.add_argument('--planar-flag',required=True,type=int,choices=(1,))
    p.add_argument('--qualification-report',required=True,type=Path)
    p.add_argument('--qualification-sha256',required=True)
    args=p.parse_args();proof=validate_args(args)
    print(json.dumps({'canonical_EL_qualification':proof}),flush=True)
    run_configured_matrix(args,config_paths(args),'el-qsv-canonical-planar1',
        lambda flag:f'EL_QSV={flag} async_depth=1 BL_unchanged=1 planar=1 other_optimizations=0',
        make_validator(1))


if __name__=='__main__':main()
