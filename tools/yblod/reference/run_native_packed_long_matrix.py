"""Output-qualified longer native packed/composed ABBA playback; no forced recovery."""
import copy
import json
from pathlib import Path

from run_colour_import_matrix import fields, parser, run_configured_matrix, validate_request
from run_native_packed_matrix import packed_summary, validate_packed_args, validate_packed_report
from run_nlq_playback_matrix import validate_lut_report


def long_packed_summary(lines, flag, allow_mixed=False):
    if not allow_mixed or not flag:
        return packed_summary(lines, flag)
    required = ('prepared', 'direct', 'composed', 'presented', 'presentation_failures', 'stage_failures')
    rows = [fields(line) for line in lines if 'DVBridge renderer summary:' in line]
    if len(rows) < 2 or any(not all(key in row for key in required) for row in rows):
        raise ValueError('Missing complete renderer route observations')
    counters = [{key: int(row[key]) for key in required} for row in rows]
    for index, row in enumerate(counters):
        if (any(value < 0 for value in row.values()) or row['direct'] + row['composed'] != row['prepared'] or
                row['presentation_failures'] or row['stage_failures'] or
                (index and any(row[key] < counters[index-1][key] for key in required))):
            raise ValueError('Invalid, failed or regressed mixed renderer route counters')
    delta = {key: counters[-1][key] - counters[0][key] for key in required}
    if delta['direct'] < 240 or delta['presented'] < 240:
        raise ValueError('Insufficient successful packed output in mixed-route case')
    return dict(requested_flag=flag, first=counters[0], last=counters[-1], interval_delta=delta,
                observations=len(counters), packed_preparation_percent=100*delta['direct']/delta['prepared'],
                mixed_routes_observed=delta['composed'] > 0,
                scope='Actual renderer preparations, not unique display flips. Mixed work is allowed explicitly; no subtitle/overlay cause is inferred.')


def validate_long_report(report, stopped, flag, binary_hash, allow_mixed=False):
    if not allow_mixed:
        return validate_packed_report(report, stopped, flag, binary_hash)
    if any('DVBridge native packed output failed' in line for line in
           report['selected_log_lines'] + report.get('route_log_lines', [])):
        raise ValueError('Native packed output fell back to composition')
    result = validate_lut_report(report, stopped, 1, binary_hash)
    result['packed_output'] = long_packed_summary(report['selected_log_lines'], flag, True)
    conversions = [fields(line) for line in report.get('route_log_lines', []) if 'DVBridge conversion:' in line]
    if not conversions or any(row.get('active') != 'release-rgb' for row in conversions):
        raise ValueError('Actual colour math was not exclusively release-RGB')
    result['colour_conversion'] = 'release-rgb'
    return result


def argument_parser():
    result = parser()
    result.set_defaults(seconds=600, seek_seconds=1200)
    result.add_argument('--preservation-report', action='append', type=Path, required=True,
                        help='Passed native composed/packed frame JSON associated with this candidate binary; may repeat.')
    result.add_argument('--allow-mixed-overlay-routes', action='store_true',
                        help='Explicitly qualify mixed packed/composed candidate playback; report actual route exposure, not exclusive packed performance or overlay causation.')
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
                          seek_seconds=args.seek_seconds, mixed_routes_allowed=args.allow_mixed_overlay_routes)), flush=True)
    validator = validate_packed_report if not args.allow_mixed_overlay_routes else \
        lambda report, stopped, flag, binary_hash: validate_long_report(report, stopped, flag, binary_hash, True)
    run_configured_matrix(args,
        [args.config_dir / f'native-packed-{flag}.conf' for flag in (0, 1)],
        f'native-packed-long-movie{args.movie_id}',
        lambda flag: f'native-fp32-lut release-rgb packed_output={flag}',
        validator)


if __name__ == '__main__':
    main()
