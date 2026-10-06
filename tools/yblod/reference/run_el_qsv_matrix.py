"""Exact-qualified isolated EL decoder SPR180 ABBA; BL decoder unchanged."""
import json
import math
from pathlib import Path
from el_qsv_qualification import qualify_report
from el_qsv_telemetry import qualify_actual_el_use
from native_optimization_telemetry import qualify_actual_use
from observe_subtitle_fixture import validate_fixture
from run_colour_import_matrix import parser, run_configured_matrix, validate_request
from run_native_planar_matrix import validate_planar_report


def config_paths(args):
    return [args.config_dir/f'native-el-qsv-planar{args.planar_flag}-flag{flag}.conf' for flag in (0, 1)]


def validate_configs(paths, planar, capture=False, selected_flags=(0, 1)):
    normalized = []
    if type(planar) is not int or planar not in (0, 1) or len(paths) != len(selected_flags):
        raise ValueError('Explicit matching planar/config selection required')
    for flag, path in zip(selected_flags, paths):
        if type(flag) is not int or flag not in (0, 1):
            raise ValueError('Explicit EL decoder0/1 required')
        lines = path.read_text().splitlines()
        wanted = dict(DVBRIDGE_FEL_QSV=flag, DVBRIDGE_NATIVE_RECONSTRUCTION=1,
            DVBRIDGE_NATIVE_DIAGNOSTICS=1, DVBRIDGE_NATIVE_FP32=1,
            DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT=1, DVBRIDGE_NATIVE_NLQ_LUT=1,
            DVBRIDGE_NATIVE_PACKED_OUTPUT=1, DVBRIDGE_NATIVE_PLANAR_OUTPUT=planar,
            DVBRIDGE_NATIVE_BATCHED_PLANES=0, DVBRIDGE_NATIVE_IMMUTABLE_INSTRUCTIONS=0,
            DVBRIDGE_CAPTURE_OUTPUTS=int(capture), DVBRIDGE_CAPTURE_PAIRS=0)
        for name, value in wanted.items():
            prefix = f'Environment={name}='
            if lines.count(prefix+str(value)) != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Unexpected decoder, composer, capture or optimization flag')
        normalized.append([line for line in lines if line != f'Environment=DVBRIDGE_FEL_QSV={flag}'])
    if any(lines != normalized[0] for lines in normalized[1:]):
        raise ValueError('Only EL decoder selection may differ')


def validate_args(args):
    validate_request(args)
    if (args.seconds != 180 or args.movie_id != 3391 or args.expected_title != 'Saving Private Ryan' or
            args.seek_seconds != 1200 or args.subtitles_off is not True or
            args.observer.name != 'observe_el_qsv_movie.py'):
        raise ValueError('Use the additive EL observer and subtitle-free matched SPR180 scene')
    validate_configs(config_paths(args), args.planar_flag)
    return qualify_report(args.qualification_report, args.baseline_binary_sha256,
                          args.binary_sha256, args.planar_flag)


def make_validator(planar):
    original = None
    def validate(report, stopped, enabled, binary_hash):
        nonlocal original
        if any(report.get(key) != value for key, value in dict(movie_id=3391,
                media='Saving Private Ryan', requested_seconds=180, seek_seconds=1200,
                expected_route='fp32').items()):
            raise ValueError('Wrong observed source scene or duration')
        validate_fixture(report.get('subtitle_fixture'), 3391)
        state = report['subtitle_fixture']['before']
        if original is not None and state != original:
            raise ValueError('Original subtitle state differs between cases')
        result = validate_planar_report(report, stopped, planar, binary_hash)
        validate_intervals(report, result)
        result['EL_decoder'] = qualify_actual_el_use(report['selected_log_lines'], enabled)
        # Both previously tested scheduling flags are deliberately OFF for the
        # first decoder comparison. Require their actual successful-use stats.
        result['other_native_optimizations'] = qualify_actual_use(
            report['selected_log_lines'], 'batched_planes', 0)
        original = dict(state)
        return result
    return validate


def validate_intervals(report, qualification):
    def bounded(value, minimum):
        return type(value) in (int, float) and math.isfinite(value) and value >= minimum
    if not bounded(report.get('elapsed_seconds'), 180) or not bounded(
            qualification.get('whole_process_cpu', {}).get('elapsed_seconds'), 150):
        raise ValueError('Full180-second observation and substantial weighted CPU interval required')
    intervals = report.get('gpu_intervals')
    if not isinstance(intervals, list):
        raise ValueError('Actual process-client GPU intervals required')
    covered = 0
    for interval in intervals:
        if not isinstance(interval, dict):
            raise ValueError('Invalid GPU interval')
        if 'unavailable' in interval:
            continue
        if not bounded(interval.get('elapsed_seconds'), .000001) or not isinstance(
                interval.get('engine_busy_percent'), dict) or not interval['engine_busy_percent']:
            raise ValueError('Invalid GPU timing or engine counters')
        if any(not bounded(value, 0) for value in interval['engine_busy_percent'].values()):
            raise ValueError('Invalid GPU engine percentage')
        covered += interval['elapsed_seconds']
    if covered < 150:
        raise ValueError('Substantial actual GPU counter coverage required')


def main():
    argument_parser = parser()
    argument_parser.set_defaults(seconds=180, seek_seconds=1200)
    argument_parser.add_argument('--planar-flag', required=True, type=int, choices=(0, 1))
    argument_parser.add_argument('--baseline-binary-sha256', required=True)
    argument_parser.add_argument('--qualification-report', required=True, type=Path)
    args = argument_parser.parse_args()
    proof = validate_args(args)
    print(json.dumps(dict(exact_EL_qualification=proof)), flush=True)
    run_configured_matrix(args, config_paths(args), f'el-qsv-planar{args.planar_flag}',
        lambda flag: f'EL_QSV={flag} async_depth=1 BL_unchanged=1 planar={args.planar_flag} other_optimizations=0',
        make_validator(args.planar_flag))


if __name__ == '__main__':
    main()
