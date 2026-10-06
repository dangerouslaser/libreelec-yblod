"""Qualify and sanitize a completed longer same-binary packed-output ABBA test."""
import argparse
import json
import math
from pathlib import Path
import re

from run_colour_import_matrix import CRASH, NATIVE_FAILURE
from run_native_packed_matrix import validate_packed_report
from summarize_long_playback import summarize
from summarize_native_packed_matrix import SHUTDOWN, pool, qualify_stage_window, raw_health_summary


def aggregate(root, binary_hash, movie_id, title, seconds=600, seek_seconds=1200):
    if (not re.fullmatch(r'[a-f0-9]{64}', binary_hash) or
            {51: '1917', 3391: 'Saving Private Ryan'}.get(movie_id) != title or
            not 300 <= seconds <= 900 or not 0 <= seek_seconds <= 14400):
        raise ValueError('Invalid candidate hash, title or bounded long-playback request')
    prefix = f'native-packed-long-movie{movie_id}'
    stems = [f'{prefix}-{order}-flag{flag}' for order, flag in enumerate((0, 1, 1, 0), 1)]
    if {path.name for path in root.glob(f'{prefix}-*-flag?.json')} != {stem+'.json' for stem in stems}:
        raise ValueError('Exactly four expected ABBA observer reports required')
    cases = []
    for order, (stem, flag) in enumerate(zip(stems, (0, 1, 1, 0)), 1):
        raw = json.loads((root/(stem+'.json')).read_text())
        if (raw.get('label') != stem or raw.get('media') != title or raw.get('movie_id') != movie_id or
                raw.get('seek_seconds') != seek_seconds or raw.get('requested_seconds') != seconds or
                raw.get('expected_route') != 'fp32'):
            raise ValueError('Wrong long-case label, movie, scene, duration or reconstruction route')
        elapsed = raw.get('elapsed_seconds')
        if not isinstance(elapsed, (float, int)) or not math.isfinite(elapsed) or elapsed < seconds:
            raise ValueError('Observer did not cover the requested long duration')
        stopped = json.loads((root/(stem+'.json.stop.json')).read_text())
        qualification = validate_packed_report(raw, stopped, flag, binary_hash)
        journal = (root/(stem+'.journal.log')).read_text()
        kodi = (root/(stem+'.kodi.log')).read_text()
        shutdown = json.loads((root/(stem+'.shutdown.json')).read_text())
        if (CRASH.search(journal) or NATIVE_FAILURE.search(kodi) or
                'DVBridge native packed output failed' in kodi or
                'Deactivated successfully' not in journal or shutdown != SHUTDOWN):
            raise ValueError('Incomplete or failed lifecycle qualification')
        if 'DVBridge output capture:' in kodi or 'DVBridge capture pair:' in kodi:
            raise ValueError('Readback capture occurred during a performance case')
        summary = summarize(raw)
        health = summary['health']
        if (not health or not health['counter_window_valid'] or not health['normal_speed'] or
                health['source_seconds'] < seconds - 30):
            raise ValueError('Missing or insufficient steady long-playback health window')
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
    return dict(schema='yblod.native-packed-long-playback-comparison.v1',
                content=title, movie_id=movie_id, seek_seconds=seek_seconds, seconds_per_case=seconds,
                matrix=[0, 1, 1, 0], same_installed_binary=True, binary_sha256=binary_hash,
                before=pool(cases, 0), after=pool(cases, 1), cases=cases,
                scopes=['Native FP32/LUT, metadata-only handoff and release-RGB colour math in both conditions.',
                        'Exact frame preservation is separately qualified, not established by playback counters.',
                        'GPU is time-weighted deduplicated Kodi DRM client activity; CPU is all Kodi threads normalized to one core.',
                        'Helper timing is cumulative-sum subtraction weighted by released operations, not latency percentiles or HDMI flips.',
                        'Raw startup/seek drop/skip maxima remain separate from steady-window deltas.',
                        'Whole-service memory snapshots/peaks are not engine-only usage.',
                        'Readback capture logs are rejected; requested duration, source progress and all four clean lifecycles must qualify.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--movie-id', required=True, type=int)
    parser.add_argument('--expected-title', required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--seek-seconds', type=int, default=1200)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.root, args.binary_sha256, args.movie_id,
                              args.expected_title, args.seconds, args.seek_seconds), indent=2, allow_nan=False))
