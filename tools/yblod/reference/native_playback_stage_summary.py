"""Summarize observer JSON without exposing raw logs, paths or process identity."""
import argparse
import datetime
import json
import math
import re
from pathlib import Path

STAGES = ('scaler_submit', 'va_wait', 'imports', 'prep_submit', 'prep_wait',
          'composer_submit', 'composer_wait', 'ycc_submit', 'ycc_wait',
          'bridge', 'consumer_release')

def health_window(report):
    rows=[]
    elapsed=0
    for line in report['selected_log_lines']:
        if 'DVBridge playback health:' not in line: continue
        fields=dict(re.findall(r'(\w+)=([^\s]+)',line))
        elapsed+=int(fields['interval_ms'])/1000
        rows.append((elapsed,fields))
    selected=[r for r in rows if 9.5<=r[0]<=70.5]
    if len(selected)<2: return {'unavailable':'Insufficient health snapshots'}
    first,last=selected[0],selected[-1]
    intervals=selected[1:]
    duration=sum(int(r[1]['interval_ms']) for r in intervals)
    return {'approximate_elapsed_start_end_seconds':[first[0],last[0]],
            'drop_delta':int(last[1]['drop_total'])-int(first[1]['drop_total']),
            'skip_delta':int(last[1]['skip_total'])-int(first[1]['skip_total']),
            'interval_weighted_render_avg_percent':sum(float(r[1]['render_avg_pct'])*int(r[1]['interval_ms']) for r in intervals)/duration,
            'source_fps':float(last[1]['source_fps']),
            'speed':int(last[1]['speed']),
            'stalled_any':any(r[1]['stalled']=='true' for r in selected),
            'scope':'Health counter differences and interval-weighted render diagnostics; attempts are not unique frame or HDMI counts.'}

def gpu_window(report):
    samples=report.get('gpu_samples',[])
    intervals=report.get('gpu_intervals',[])
    anchor=report.get('observer_started_monotonic_ns')
    durations=[]
    sums={}
    unavailable=0
    for index, interval in enumerate(intervals):
        if anchor is None:
            start,end=2*(index+1),2*(index+2)
        else:
            start=(samples[index]['monotonic_ns']-anchor)/1e9
            end=(samples[index+1]['monotonic_ns']-anchor)/1e9
        if not (start>=10 and end<=70): continue
        if 'unavailable' in interval:
            unavailable+=1
            continue
        duration=interval['elapsed_seconds']
        durations.append(duration)
        for name,value in interval['engine_busy_percent'].items():
            sums[name]=sums.get(name,0)+value*duration
    if not durations:return {'unavailable':'No valid selected GPU intervals'}
    return {'selected_interval_seconds':sum(durations),'valid_intervals':len(durations),
            'unavailable_intervals':unavailable,
            'interval_weighted_engine_busy_percent':{k:v/sum(durations) for k,v in sums.items()},
            'anchor_scope':'Exact saved observer monotonic anchor; fully contained10–70s intervals' if anchor is not None else 'Approximate ordinal2s sample anchor; baseline has no saved observer start timestamp',
            'scope':'Kodi DRM client engine busy diagnostics; not reconstruction-only GPU time.'}

def summarize(report):
    lines = report['selected_log_lines']
    first = next((line for line in lines if 'DVBridge first frame:' in line), None)
    def timestamp(line):
        return datetime.datetime.fromisoformat(line[:23])
    origin = timestamp(first) if first else None
    snapshots = []
    for line in lines:
        if 'DVBridge native timing:' not in line:
            continue
        fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
        # Production logs uint32 valid=1; accept textual true for older fixtures.
        if fields.get('valid') not in ('1', 'true') or not all(s in fields for s in STAGES):
            raise ValueError('Invalid or incomplete timing snapshot')
        count = int(fields['released_frames'])
        if count <= 0 or count % 120 or snapshots and count <= snapshots[-1]['released_frames']:
            raise ValueError('Timing release count reset or duplicated')
        means = {s: float(fields[s]) for s in STAGES}
        if not all(math.isfinite(v) and v >= 0 for v in means.values()):
            raise ValueError('Nonfinite or negative stage mean')
        snapshots.append({'released_frames': count,
                          'elapsed_from_first_frame_seconds': (timestamp(line)-origin).total_seconds() if origin else None,
                          'rounded_cumulative_ms_per_released_frame': means})
    summary = {'schema': 'yblod.playback-stage-summary.v1',
               'failure_marker': report['failure_marker'],
               'service_identity_unchanged': report['kodi_before'] == report['kodi_after'],
               'scope': 'Host helper-call wall time per released native frame; not GPU kernel, full render budget, unique frames or HDMI output.',
               'stage_snapshots': snapshots,
               'timing_precision': 'Logged cumulative means are rounded to 0.001 ms; reconstructed window estimates are not original nanosecond totals.'}
    valid_run = summary['service_identity_unchanged'] and not summary['failure_marker'] and not report.get('log_rotated_or_truncated', False)
    summary['comparison_valid'] = valid_run
    candidates = [s for s in snapshots if valid_run and s['elapsed_from_first_frame_seconds'] is not None
                  and 10 <= s['elapsed_from_first_frame_seconds'] <= 70]
    if len(candidates) >= 2:
        a, b = candidates[0], candidates[-1]
        n0, n1 = a['released_frames'], b['released_frames']
        means0, means1 = a['rounded_cumulative_ms_per_released_frame'], b['rounded_cumulative_ms_per_released_frame']
        summary['approximate_steady_stage_window'] = {
            'release_count_start_end': [n0, n1],
            'elapsed_from_first_frame_start_end_seconds': [a['elapsed_from_first_frame_seconds'], b['elapsed_from_first_frame_seconds']],
            'estimated_ms_per_released_frame': {s: (n1*means1[s]-n0*means0[s])/(n1-n0) for s in STAGES},
            'per_stage_rounding_error_bound_ms_per_released_frame': 0.0005*(n1+n0)/(n1-n0),
            'scope': 'Between available snapshots inside approximate first-frame-relative 10–70 s window, not exact observer wall window.'}
    elif not valid_run:
        summary['stage_window_unavailable'] = 'Service identity changed, failure marker or log discontinuity; no inferred steady window.'
    elif snapshots:
        summary['stage_window_unavailable'] = 'Fewer than two valid snapshots in approximate 10–70 s window; last snapshot is cumulative only.'
    else:
        summary['stage_window_unavailable'] = 'No valid native timing snapshots.'
    return summary

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('observer_report', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.observer_report.read_text())), indent=2))
