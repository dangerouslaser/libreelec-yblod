"""Output-qualified native planar-fusion SPR ABBA test; no forced recovery."""
import json
from pathlib import Path

from run_colour_import_matrix import fields, parser, run_configured_matrix, validate_request
from run_native_packed_matrix import packed_summary, validate_packed_report


def planar_summary(lines, flag):
    summary = packed_summary(lines, 1)
    rows = [fields(line) for line in lines if 'DVBridge renderer summary:' in line]
    if flag not in (0, 1) or any('native_planar' not in row for row in rows):
        raise ValueError('Missing actual native planar preparation evidence')
    counts = [int(row['native_planar']) for row in rows]
    if (any(count < 0 or count > int(row['prepared']) for count, row in zip(counts, rows)) or
            any(b < a for a, b in zip(counts, counts[1:]))):
        raise ValueError('Invalid or regressed native planar counters')
    delta = counts[-1] - counts[0]
    if (not flag and any(counts)) or (flag and delta != summary['interval_delta']['prepared']):
        raise ValueError('Actual native planar work did not exclusively match requested flag')
    return dict(requested_planar_flag=flag, first_count=counts[0], last_count=counts[-1],
                preparation_count_delta=delta,
                planar_preparation_percent=100*delta/summary['interval_delta']['prepared'],
                packed_output=summary)


def planar_preservation_report(path):
    report = json.loads(path.read_text())
    for phase, planar in (('before', 0), ('after', 1)):
        route = report.get(phase, {})
        if route.get('native') != 1 or route.get('direct_packed') != 1 or route.get('native_planar') != planar:
            raise ValueError('Frame qualification lacks native packed planar OFF/ON route evidence')
    if (report.get('schema') != 'yblod.renderer-output-comparison.v1' or
            report.get('identical_source_layer_timestamps') is not True or
            report.get('identical_source_metadata') is not True):
        raise ValueError('Missing identical-source planar preservation qualification')
    for phase in ('before', 'after'):
        if int(report[phase].get('valid_leading_packets', 0)) <= 0:
            raise ValueError('Missing validated planar transport packets')
    semantic = report.get('picture_and_payload_preservation') or {}
    if report.get('output_preserved') is not True and semantic.get('picture_and_payload_preserved') is not True:
        raise ValueError('Planar output preservation has not passed')
    planes = report.get('planes', {})
    if set(planes) != {'I', 'P', 'T'} or any(plane.get('max_absolute_codes') != 0 or
            plane.get('exact_percent') != 100 for plane in planes.values()):
        raise ValueError('Planar picture code values changed')
    return dict(all_tunnel_rgb_bytes_identical=report['output_preserved'],
                picture_and_payload_preserved=semantic.get('picture_and_payload_preserved', False),
                native_planar_before=0, native_planar_after=1,
                scope='Supplied frame qualification; caller must associate it with this candidate binary.')


def validate_planar_report(report, stopped, flag, binary_hash):
    result = validate_packed_report(report, stopped, 1, binary_hash)
    result['native_planar'] = planar_summary(report['selected_log_lines'], flag)
    return result


def validate_planar_args(args):
    validate_request(args)
    if (args.seconds != 180 or args.movie_id != 3391 or
            args.expected_title != 'Saving Private Ryan' or args.seek_seconds != 1200):
        raise ValueError('Use matched 180-second Saving Private Ryan windows at 20 minutes')
    normalized = []
    for flag in (0, 1):
        lines = (args.config_dir/f'native-planar-{flag}.conf').read_text().splitlines()
        marker = f'Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT={flag}'
        if lines.count(marker) != 1 or sum(line.startswith('Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT=') for line in lines) != 1:
            raise ValueError('Wrong native planar flag')
        for name in ('RECONSTRUCTION', 'DIAGNOSTICS', 'FP32', 'COLOUR_NO_REIMPORT', 'NLQ_LUT', 'PACKED_OUTPUT'):
            prefix = f'Environment=DVBRIDGE_NATIVE_{name}='
            if lines.count(prefix+'1') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Both cases require native FP32/LUT/handoff and packed output')
        for name in ('OUTPUTS', 'PAIRS'):
            prefix = f'Environment=DVBRIDGE_CAPTURE_{name}='
            if lines.count(prefix+'0') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Capture must be disabled during performance measurements')
        normalized.append([line for line in lines if line != marker])
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond the native planar flag')
    if not args.preservation_report:
        raise ValueError('Pixel preservation must qualify before planar performance tests')
    return [planar_preservation_report(path) for path in args.preservation_report]


def main():
    argument_parser = parser()
    argument_parser.set_defaults(seconds=180, seek_seconds=1200)
    argument_parser.add_argument('--preservation-report', action='append', type=Path, required=True)
    args = argument_parser.parse_args()
    qualified = validate_planar_args(args)
    print(json.dumps(dict(output_preservation_qualified=qualified)), flush=True)
    run_configured_matrix(args,
        [args.config_dir/f'native-planar-{flag}.conf' for flag in (0, 1)],
        'native-planar', lambda flag: f'native-fp32-lut release-rgb packed_output=1 native_planar={flag}',
        validate_planar_report)


if __name__ == '__main__':
    main()
