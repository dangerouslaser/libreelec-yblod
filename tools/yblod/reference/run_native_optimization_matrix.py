"""Exact-frame-qualified isolated-option SPR180 ABBA; no forced recovery."""
import json
from pathlib import Path

from native_optimization_qualification import OPTIONS, qualify_frames
from observe_subtitle_fixture import validate_fixture
from run_colour_import_matrix import parser, run_configured_matrix, validate_request
from run_native_planar_matrix import validate_planar_report

ENV = dict(batched_planes='DVBRIDGE_NATIVE_BATCHED_PLANES',
           immutable_instructions='DVBRIDGE_NATIVE_IMMUTABLE_INSTRUCTIONS')


def config_paths(args):
    return [args.config_dir/'native-optimization-baseline.conf',
            args.config_dir/('native-optimization-'+args.optimization.replace('_', '-')+'.conf')]


def validate_args(args):
    validate_request(args)
    if (args.optimization not in OPTIONS or args.seconds != 180 or args.movie_id != 3391 or
            args.expected_title != 'Saving Private Ryan' or args.seek_seconds != 1200 or
            getattr(args, 'subtitles_off', False) is not True):
        raise ValueError('Use isolated subtitle-free SPR180 windows at twenty minutes')
    normalized = []
    for enabled, path in enumerate(config_paths(args)):
        lines = path.read_text().splitlines()
        selected_marker = f'Environment={ENV[args.optimization]}={enabled}'
        for option, name in ENV.items():
            prefix = f'Environment={name}='
            expected = enabled if option == args.optimization else 0
            if lines.count(prefix+str(expected)) != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Only selected optimization may be enabled')
        for name in ('RECONSTRUCTION', 'DIAGNOSTICS', 'FP32', 'COLOUR_NO_REIMPORT',
                     'NLQ_LUT', 'PACKED_OUTPUT', 'PLANAR_OUTPUT'):
            prefix = f'Environment=DVBRIDGE_NATIVE_{name}='
            if lines.count(prefix+'1') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Native FP32/LUT/metadata-only packed planar route required in both')
        for name in ('OUTPUTS', 'PAIRS'):
            prefix = f'Environment=DVBRIDGE_CAPTURE_{name}='
            if lines.count(prefix+'0') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('No capture readback during performance measurement')
        normalized.append([line for line in lines if line != selected_marker])
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond selected optimization')
    if not args.preservation_report:
        raise ValueError('Exact matched same-candidate frame proof required before performance')
    return [qualify_frames(path, args.binary_sha256, args.optimization) for path in args.preservation_report]


def make_validator(option, qualify_actual_use):
    original = None
    def validate(report, stopped, enabled, binary_hash):
        nonlocal original
        validate_fixture(report.get('subtitle_fixture'), 3391)
        state = report['subtitle_fixture']['before']
        if original is not None and state != original:
            raise ValueError('Original subtitle state differs across matched cases')
        result = validate_planar_report(report, stopped, 1, binary_hash)
        result['native_optimization'] = qualify_actual_use(report['selected_log_lines'], option, enabled)
        original = dict(state)
        return result
    return validate


def main():
    argument_parser = parser()
    argument_parser.set_defaults(seconds=180, seek_seconds=1200)
    argument_parser.add_argument('--optimization', required=True, choices=OPTIONS)
    argument_parser.add_argument('--preservation-report', action='append', type=Path, required=True)
    args = argument_parser.parse_args()
    proof = validate_args(args)
    # Actual-use telemetry must be supplied by the matching implementation;
    # fail closed rather than accepting environment flags as proof of use.
    from native_optimization_telemetry import qualify_actual_use
    print(json.dumps(dict(output_preservation_qualified=proof)), flush=True)
    run_configured_matrix(args, config_paths(args), 'native-optimization-'+args.optimization,
        lambda enabled: f'{args.optimization}={enabled} other_optimization=0 planar=1 packed=1',
        make_validator(args.optimization, qualify_actual_use))


if __name__ == '__main__':
    main()
