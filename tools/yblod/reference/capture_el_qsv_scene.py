"""Add strict actual EL route admission to the existing bounded SPR capture."""
import argparse
import re
import sys
import capture_scene
from el_qsv_qualification import route


def request(argv):
    parser = argparse.ArgumentParser(description=__doc__ + ' Remaining flags go to capture_scene.py.')
    parser.add_argument('--el-qsv-flag', required=True, type=int, choices=(0, 1))
    parser.add_argument('--planar-flag', required=True, type=int, choices=(0, 1))
    selected, remaining = parser.parse_known_args(argv)
    args = capture_scene.parse_args(remaining)
    if (not isinstance(args.binary_sha256, str) or not re.fullmatch('[a-f0-9]{64}', args.binary_sha256) or
            args.movie_id != 3391 or args.expected_title != 'Saving Private Ryan' or args.file or
            args.seek_seconds != 1200 or args.subtitles_off is not True or args.view_zoom is not None):
        raise ValueError('Exact binary, SPR twenty-minute scene and restored subtitle-free fixture required')
    wanted = dict(expected_native=1, expected_direct_packed=1, expected_native_planar=selected.planar_flag,
                  expected_batched_planes=0, expected_immutable_instructions=0)
    if any(getattr(args, key) != value for key, value in wanted.items()):
        raise ValueError('Explicit matching native packed/planar route expectations required')
    from run_el_qsv_matrix import validate_configs
    validate_configs([args.config], selected.planar_flag, capture=True,
                     selected_flags=(selected.el_qsv_flag,))
    return selected, args


def main(argv=None):
    selected, args = request(sys.argv[1:] if argv is None else argv)
    old_parser, old_route = capture_scene.parse_args, capture_scene.verify_capture_route
    def verify(info, parsed):
        old_route(info, parsed)
        route(info, selected.el_qsv_flag, selected.planar_flag)
    try:
        capture_scene.parse_args = lambda: args
        capture_scene.verify_capture_route = verify
        capture_scene.main()
    finally:
        capture_scene.parse_args, capture_scene.verify_capture_route = old_parser, old_route


if __name__ == '__main__':
    main()
