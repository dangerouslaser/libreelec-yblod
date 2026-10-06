"""Output-qualified longer native packed/composed ABBA playback; no forced recovery."""
import copy
import json
from pathlib import Path

from run_colour_import_matrix import parser, run_configured_matrix, validate_request
from run_native_packed_matrix import validate_packed_args, validate_packed_report


def argument_parser():
    result = parser()
    result.set_defaults(seconds=600, seek_seconds=1200)
    result.add_argument('--preservation-report', action='append', type=Path, required=True,
                        help='Passed native composed/packed frame JSON associated with this candidate binary; may repeat.')
    return result


def validate_long_args(args):
    validate_request(args)
    if not 300 <= args.seconds <= 900 or {51: '1917', 3391: 'Saving Private Ryan'}.get(args.movie_id) != args.expected_title:
        raise ValueError('Use bounded 300–900 second matched windows for 1917 or Saving Private Ryan')
    qualification_args = copy.copy(args)
    qualification_args.seconds = 180
    qualification_args.movie_id = 3391
    qualification_args.expected_title = 'Saving Private Ryan'
    qualification_args.seek_seconds = 1200
    return validate_packed_args(qualification_args)


def main():
    args = argument_parser().parse_args()
    qualified = validate_long_args(args)
    print(json.dumps(dict(output_preservation_qualified=qualified, movie_id=args.movie_id,
                          expected_title=args.expected_title, seconds=args.seconds,
                          seek_seconds=args.seek_seconds)), flush=True)
    run_configured_matrix(args,
        [args.config_dir / f'native-packed-{flag}.conf' for flag in (0, 1)],
        f'native-packed-long-movie{args.movie_id}',
        lambda flag: f'native-fp32-lut release-rgb packed_output={flag}',
        validate_packed_report)


if __name__ == '__main__':
    main()
