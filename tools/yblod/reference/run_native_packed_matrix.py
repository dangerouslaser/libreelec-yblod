"""Output-qualified native packed/composed SPR ABBA test; no forced recovery."""
import json
from pathlib import Path

from run_colour_import_matrix import fields, parser, run_configured_matrix, validate_request
from run_nlq_playback_matrix import validate_lut_report


def packed_summary(lines, flag):
    rows = [fields(line) for line in lines if 'DVBridge renderer summary:' in line]
    required = ('prepared', 'direct', 'composed', 'presented',
                'presentation_failures', 'stage_failures')
    if len(rows) < 2 or flag not in (0, 1):
        raise ValueError('Missing substantial renderer route evidence')
    counters = []
    for row in rows:
        if not all(key in row for key in required):
            raise ValueError('Incomplete renderer counter schema')
        counts = {key: int(row[key]) for key in required}
        if (any(value < 0 for value in counts.values()) or
                counts['direct'] + counts['composed'] != counts['prepared'] or
                counts['presentation_failures'] or counts['stage_failures']):
            raise ValueError('Invalid or failed renderer work')
        if not flag and counts['direct']:
            raise ValueError('Packed work occurred in the disabled native control')
        if counters and any(counts[key] < counters[-1][key] for key in required):
            raise ValueError('Renderer counters reset or regressed')
        counters.append(counts)
    delta = {key: counters[-1][key] - counters[0][key] for key in required}
    if delta['prepared'] < 240 or delta['presented'] < 240:
        raise ValueError('Insufficient successful renderer interval')
    if flag and delta['direct'] != delta['prepared']:
        raise ValueError('Candidate did not exclusively use packed output after initial summary')
    if not flag and delta['composed'] != delta['prepared']:
        raise ValueError('Control did not exclusively use composition')
    return dict(requested_flag=flag, first=counters[0], last=counters[-1],
                interval_delta=delta, observations=len(counters),
                packed_preparation_percent=100 * delta['direct'] / delta['prepared'],
                scope='Renderer preparations between first and last summary, not unique HDMI flips; '
                      'startup GUI may compose before the first summary.')


def preservation_report(path):
    report = json.loads(path.read_text())
    if (report.get('schema') != 'yblod.renderer-output-comparison.v1' or
            report.get('identical_source_layer_timestamps') is not True or
            report.get('identical_source_metadata') is not True):
        raise ValueError('Missing identical-source preservation qualification')
    for phase, packed in (('before', 0), ('after', 1)):
        route = report.get(phase, {})
        if route.get('native') != 1 or route.get('direct_packed') != packed:
            raise ValueError('Preservation comparison is not native composed versus native packed')
        if int(route.get('valid_leading_packets', 0)) <= 0:
            raise ValueError('Preservation capture lacks validated transport packets')
    semantic = report.get('picture_and_payload_preservation') or {}
    if (report.get('output_preserved') is not True and
            semantic.get('picture_and_payload_preserved') is not True):
        raise ValueError('Output preservation has not passed')
    planes = report.get('planes', {})
    if set(planes) != {'I', 'P', 'T'} or any(
            plane.get('max_absolute_codes') != 0 or plane.get('exact_percent') != 100
            for plane in planes.values()):
        raise ValueError('Picture code values changed')
    return {'all_tunnel_rgb_bytes_identical': report['output_preserved'],
            'picture_and_payload_preserved': semantic.get('picture_and_payload_preserved', False),
            'scope': 'Supplied frame qualification; caller must associate it with this candidate binary.'}


def validate_packed_report(report, stopped, flag, binary_hash):
    if any('DVBridge native packed output failed' in line for line in
           report['selected_log_lines'] + report.get('route_log_lines', [])):
        raise ValueError('Native packed output fell back to composition')
    result = validate_lut_report(report, stopped, 1, binary_hash)
    result['packed_output'] = packed_summary(report['selected_log_lines'], flag)
    conversions = [fields(line) for line in report.get('route_log_lines', [])
                   if 'DVBridge conversion:' in line]
    if not conversions or any(row.get('active') != 'release-rgb' for row in conversions):
        raise ValueError('Actual colour math was not exclusively release-RGB')
    result['colour_conversion'] = 'release-rgb'
    return result


def validate_packed_args(args):
    validate_request(args)
    if (args.seconds != 180 or args.movie_id != 3391 or
            args.expected_title != 'Saving Private Ryan' or args.seek_seconds != 1200):
        raise ValueError('Use matched 180-second Saving Private Ryan windows at 20 minutes')
    normalized = []
    for flag in (0, 1):
        lines = (args.config_dir / f'native-packed-{flag}.conf').read_text().splitlines()
        marker = f'Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT={flag}'
        if (lines.count(marker) != 1 or
                sum(line.startswith('Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT=') for line in lines) != 1):
            raise ValueError('Wrong native packed-output flag')
        for name in ('RECONSTRUCTION', 'DIAGNOSTICS', 'FP32', 'COLOUR_NO_REIMPORT', 'NLQ_LUT'):
            prefix = f'Environment=DVBRIDGE_NATIVE_{name}='
            if lines.count(prefix+'1') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Both cases require qualified native FP32/LUT/handoff')
        for name in ('OUTPUTS', 'PAIRS'):
            prefix = f'Environment=DVBRIDGE_CAPTURE_{name}='
            if lines.count(prefix+'0') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
                raise ValueError('Capture must be disabled during performance measurements')
        normalized.append([line for line in lines if line != marker])
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond the packed-output flag')
    if not args.preservation_report:
        raise ValueError('Pixel preservation must be qualified before performance tests')
    return [preservation_report(path) for path in args.preservation_report]


def main():
    argument_parser = parser()
    argument_parser.add_argument('--preservation-report', action='append', type=Path, required=True,
                                 help='Passed native composed/packed comparison JSON; may repeat.')
    args = argument_parser.parse_args()
    qualified = validate_packed_args(args)
    print(json.dumps({'output_preservation_qualified': qualified}), flush=True)
    run_configured_matrix(args,
        [args.config_dir / f'native-packed-{flag}.conf' for flag in (0, 1)],
        'native-packed', lambda flag: f'native-fp32-lut release-rgb packed_output={flag}',
        validate_packed_report)


if __name__ == '__main__':
    main()
