"""Sanitize completed observer reports; no playback, writes, or film extraction."""
import argparse
import json
import re
from pathlib import Path


def fields(line):
    return dict(re.findall(r"([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)", line))


def summarize(report):
    lines = report['selected_log_lines']
    health = [fields(line) for line in lines if 'DVBridge playback health:' in line]
    health = [entry for entry in health if int(entry['interval_ms']) > 0
              and 8 <= float(entry['pts_s']) <= 72]
    timings = [fields(line) for line in lines if 'DVBridge native timing:' in line]
    timings = [entry for entry in timings if entry.get('valid') == '1']
    result = {
        'label': report.get('label'),
        'observer_elapsed_seconds': report['elapsed_seconds'],
        'service_identity_unchanged': report['kodi_before'] == report['kodi_after'],
        'failure_marker': report['failure_marker'],
        'log_rotated_or_truncated': report['log_rotated_or_truncated'],
        'health': None,
        'stage_window': None,
        'route_observations': [fields(line) for line in lines
                               if 'fp32' in line.lower()],
        'scope': 'helper wall times and Kodi health, not exclusive GPU time, HDMI flips, or unique-frame FPS',
    }
    result['memory_snapshots'] = {}
    for phase in ('runtime_before', 'runtime_after'):
        runtime = report.get(phase, {})
        service = dict(line.split('=', 1) for line in runtime.get('service', '').splitlines()
                       if '=' in line)
        result['memory_snapshots'][phase] = {
            key: int(service[key]) for key in ('MemoryCurrent', 'MemoryPeak')
            if service.get(key, '').isdigit()}
    result['memory_snapshot_scope'] = (
        'whole Kodi service; MemoryPeak is lifetime-high-water, not per-run or engine-only; '
        'B2 may inherit B1 peak and process history')
    before_hash = report.get('runtime_before', {}).get('binary_sha256')
    after_hash = report.get('runtime_after', {}).get('binary_sha256')
    result['binary_identity_unchanged'] = bool(before_hash and before_hash == after_hash)
    if len(health) >= 2:
        first, last = health[0], health[-1]
        valid = all(entry.get('counters_reset') == 'false' for entry in health)
        interval = {
            'first_pts_s': float(first['pts_s']), 'last_pts_s': float(last['pts_s']),
            'source_seconds': float(last['pts_s']) - float(first['pts_s']),
            'counter_window_valid': valid,
            'first_drop_total': int(first['drop_total']),
            'last_drop_total': int(last['drop_total']),
            'first_skip_total': int(first['skip_total']),
            'last_skip_total': int(last['skip_total']),
            'drop_delta': int(last['drop_total']) - int(first['drop_total']) if valid else None,
            'skip_delta': int(last['skip_total']) - int(first['skip_total']) if valid else None,
            'normal_speed': all(entry.get('speed') == '1000' for entry in health),
            'stalled': any(entry.get('stalled') != 'false' for entry in health),
        }
        weighted = [(int(entry['interval_ms']), float(entry['render_avg_pct']))
                    for entry in health[1:] if entry.get('render_avg_pct') != 'unavailable']
        interval['weighted_render_avg_percent'] = (
            sum(duration * value for duration, value in weighted) /
            sum(duration for duration, _ in weighted) if weighted else None)
        result['health'] = interval
    # Each log value is a cumulative sum / released count, rounded to 0.001 ms.
    # Subtract weighted totals; never average cumulative averages directly.
    start = next((entry for entry in timings if int(entry['released_frames']) == 120), None)
    end = timings[-1] if timings else None
    if start and end:
        a, b = int(start['released_frames']), int(end['released_frames'])
        if b > a:
            names = ('scaler_submit', 'va_wait', 'imports', 'prep_submit', 'prep_wait',
                     'composer_submit', 'composer_wait', 'ycc_submit', 'ycc_wait',
                     'bridge', 'consumer_release')
            result['stage_window'] = {
                'start_released': a, 'end_released': b, 'released_count_delta': b-a,
                'wall_ms_per_release': {
                    name: (float(end[name])*b-float(start[name])*a)/(b-a)
                    for name in names if name in start and name in end},
                'worst_case_log_rounding_error_ms': 0.0005*(a+b)/(b-a),
                'released_count_is_not_unique_frames_or_display_flips': True,
            }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps({'schema': 'yblod.fp32-playback-comparison.v1',
                      'runs': [summarize(json.loads(path.read_text())) for path in args.reports]}, indent=2))
