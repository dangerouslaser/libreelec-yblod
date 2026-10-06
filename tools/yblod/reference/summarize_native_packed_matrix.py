"""Qualify and sanitize a completed same-binary native packed-output ABBA test."""
import argparse
import json
import math
from pathlib import Path
import re

from run_colour_import_matrix import CRASH, NATIVE_FAILURE, fields
from run_native_packed_matrix import validate_packed_report
from summarize_long_playback import summarize

STAGES = ('scaler_submit', 'va_wait', 'imports', 'prep_submit', 'prep_wait',
          'composer_submit', 'composer_wait', 'ycc_submit', 'ycc_wait',
          'bridge', 'consumer_release')
SHUTDOWN = dict(ActiveState='inactive', MainPID='0', Result='success',
                ExecMainCode='1', ExecMainStatus='0')


def raw_health_summary(report):
    rows = [fields(line) for line in report['selected_log_lines']
            if 'DVBridge playback health:' in line]
    required = ('pts_s', 'drop_total', 'skip_total', 'counters_reset', 'speed', 'stalled')
    if len(rows) < 2 or any(not all(key in row for key in required) for row in rows):
        raise ValueError('Missing raw playback-health observations')
    if any(not math.isfinite(float(row['pts_s'])) or
           int(row['drop_total']) < 0 or int(row['skip_total']) < 0 for row in rows):
        raise ValueError('Invalid raw playback counters')
    return dict(observations=len(rows),
                first={key: rows[0][key] for key in required},
                last={key: rows[-1][key] for key in required},
                maximum_observed_drop_total=max(int(row['drop_total']) for row in rows),
                maximum_observed_skip_total=max(int(row['skip_total']) for row in rows),
                any_counter_reset=any(row['counters_reset'] != 'false' for row in rows),
                any_stalled=any(row['stalled'] != 'false' for row in rows),
                scope='Raw cumulative observations include startup/seek; maxima are not steady-window deltas.')


def qualify_stage_window(report, summary):
    timings = [fields(line) for line in report['selected_log_lines']
               if 'DVBridge native timing:' in line]
    if len(timings) < 2:
        raise ValueError('Missing released-operation timing evidence')
    previous = None
    for row in timings:
        if row.get('valid') != '1' or not all(key in row for key in STAGES + ('released_frames',)):
            raise ValueError('Invalid or incomplete native timing schema')
        count = int(row['released_frames'])
        if count <= 0 or (previous is not None and count <= previous):
            raise ValueError('Released-operation timing counters reset or regressed')
        if any(not math.isfinite(float(row[key])) or float(row[key]) < 0 for key in STAGES):
            raise ValueError('Invalid cumulative helper timings')
        previous = count
    stage = summary['stage_window']
    if not stage or stage['released_count_delta'] < 240 or set(stage['wall_ms_per_release']) != set(STAGES):
        raise ValueError('Insufficient released-operation timing window')
    if any(value < -stage['worst_case_log_rounding_error_ms']
           for value in stage['wall_ms_per_release'].values()):
        raise ValueError('Cumulative helper timing sum regressed')
    return stage


def pool(cases, flag):
    rows = [row for row in cases if row['packed_output_flag'] == flag]
    cpu_seconds = sum(row['qualification']['whole_process_cpu']['process_cpu_seconds'] for row in rows)
    cpu_elapsed = sum(row['qualification']['whole_process_cpu']['elapsed_seconds'] for row in rows)
    gpu_elapsed = sum(row['gpu']['duration_seconds'] for row in rows)
    released = sum(row['stage']['released_count_delta'] for row in rows)
    handoff_calls = sum(row['qualification']['colour_handoff']['call_count_delta'] for row in rows)
    engines = set(rows[0]['gpu']['time_weighted_busy_percent'])
    if cpu_elapsed <= 0 or gpu_elapsed <= 0 or not engines or any(
            set(row['gpu']['time_weighted_busy_percent']) != engines for row in rows):
        raise ValueError('Missing CPU/GPU intervals or inconsistent engine sets')
    return dict(whole_kodi_cpu_percent_one_core=100*cpu_seconds/cpu_elapsed,
                cpu_elapsed_seconds=cpu_elapsed, process_cpu_seconds=cpu_seconds,
                gpu_elapsed_seconds=gpu_elapsed,
                gpu_engine_busy_percent={engine: sum(row['gpu']['duration_seconds'] *
                    row['gpu']['time_weighted_busy_percent'][engine] for row in rows)/gpu_elapsed
                    for engine in sorted(engines)},
                helper_wall_ms_per_release={name: sum(row['stage']['released_count_delta'] *
                    row['stage']['wall_ms_per_release'][name] for row in rows)/released
                    for name in STAGES},
                released_operation_count_delta=released,
                helper_log_rounding_error_ms=sum(row['stage']['released_count_delta'] *
                    row['stage']['worst_case_log_rounding_error_ms'] for row in rows)/released,
                colour_handoff_ms_per_call={key: sum(
                    row['qualification']['colour_handoff']['call_count_delta'] *
                    row['qualification']['colour_handoff']['weighted_window'][key] for row in rows)/handoff_calls
                    for key in ('wall_ms_per_call', 'thread_cpu_ms_per_call')},
                colour_handoff_call_count_delta=handoff_calls,
                health_case_totals=[dict(order=row['order'],
                    raw_maximum_drop_total=row['raw_health']['maximum_observed_drop_total'],
                    raw_maximum_skip_total=row['raw_health']['maximum_observed_skip_total'],
                    pre_steady_drop_total=row['health']['first_drop_total'],
                    pre_steady_skip_total=row['health']['first_skip_total'],
                    steady_drop_delta=row['health']['drop_delta'],
                    steady_skip_delta=row['health']['skip_delta'],
                    steady_stalled=row['health']['stalled']) for row in rows])


def aggregate(root, binary_hash):
    if not re.fullmatch(r'[a-f0-9]{64}', binary_hash):
        raise ValueError('Invalid candidate binary hash')
    cases = []
    for order, flag in enumerate((0, 1, 1, 0), 1):
        stem = f'native-packed-{order}-flag{flag}'
        raw = json.loads((root/(stem+'.json')).read_text())
        if (raw.get('media') != 'Saving Private Ryan' or raw.get('movie_id') != 3391 or
                raw.get('seek_seconds') != 1200 or raw.get('requested_seconds') != 180 or
                raw.get('expected_route') != 'fp32'):
            raise ValueError('Wrong scene, duration or reconstruction route')
        stopped = json.loads((root/(stem+'.json.stop.json')).read_text())
        qualification = validate_packed_report(raw, stopped, flag, binary_hash)
        journal = (root/(stem+'.journal.log')).read_text()
        kodi = (root/(stem+'.kodi.log')).read_text()
        shutdown = json.loads((root/(stem+'.shutdown.json')).read_text())
        if (CRASH.search(journal) or NATIVE_FAILURE.search(kodi) or
                'DVBridge native packed output failed' in kodi or
                'Deactivated successfully' not in journal or shutdown != SHUTDOWN):
            raise ValueError('Incomplete or failed lifecycle qualification')
        summary = summarize(raw)
        health = summary['health']
        if (not health or not health['counter_window_valid'] or not health['normal_speed'] or
                health['source_seconds'] <= 0):
            raise ValueError('Missing or invalid steady playback-health window')
        gpu = summary['gpu_counter_intervals']
        if gpu['valid_count'] < 2 or gpu['duration_seconds'] <= 0:
            raise ValueError('Missing substantial GPU counter observations')
        engine_sets = [set(item['engine_busy_percent']) for item in raw['gpu_intervals']
                       if 'engine_busy_percent' in item]
        if not engine_sets or any(row != engine_sets[0] for row in engine_sets):
            raise ValueError('GPU engine sets changed within a case')
        if any(not math.isfinite(value) or value < 0
               for value in gpu['time_weighted_busy_percent'].values()):
            raise ValueError('Invalid GPU busy metrics')
        cases.append(dict(order=order, packed_output_flag=flag, qualification=qualification,
                          raw_health=raw_health_summary(raw), health=health,
                          stage=qualify_stage_window(raw, summary), gpu=gpu,
                          memory=summary['memory_snapshots'], shutdown=shutdown))
    if any(set(row['gpu']['time_weighted_busy_percent']) !=
           set(cases[0]['gpu']['time_weighted_busy_percent']) for row in cases):
        raise ValueError('GPU engine sets differ across the matrix')
    return dict(schema='yblod.native-packed-playback-comparison.v1',
                content='Saving Private Ryan', seek_seconds=1200, seconds_per_case=180,
                matrix=[0, 1, 1, 0], same_installed_binary=True, binary_sha256=binary_hash,
                before=pool(cases, 0), after=pool(cases, 1), cases=cases,
                scopes=['Both conditions use native FP32/LUT reconstruction, metadata-only handoff and release-RGB colour math.',
                        'Output preservation is a separate identical-frame qualification, not established by playback counters.',
                        'GPU activity is time-weighted deduplicated Kodi DRM client activity, not exclusive shader time.',
                        'CPU includes all Kodi threads and uses one-core normalization.',
                        'Helper timings subtract cumulative sums and weight by released-operation count; they are not latency percentiles, FPS or unique HDMI frames.',
                        'Pre-steady cumulative drop/skip totals include startup/seek and possibly earlier counter history; steady deltas are reported separately.',
                        'Whole-service memory snapshots and lifetime peaks are not engine-only usage.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--binary-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.root, args.binary_sha256), indent=2, allow_nan=False))
