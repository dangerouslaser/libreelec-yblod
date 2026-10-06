"""Strict scalar-only 600-second subtitle-free planar OFF/ON ABBA summary."""
import argparse
import json
import math
from pathlib import Path
import re

from observe_subtitle_fixture import validate_fixture
from run_colour_import_matrix import CRASH, NATIVE_FAILURE
from run_native_planar_matrix import validate_planar_report
from summarize_long_playback import summarize
from summarize_native_packed_matrix import SHUTDOWN, pool, qualify_stage_window, raw_health_summary


def aggregate(root, binary_hash, movie_id, title):
    if not re.fullmatch(r'[a-f0-9]{64}', binary_hash) or {3391: 'Saving Private Ryan', 51: '1917'}.get(movie_id) != title:
        raise ValueError('Invalid candidate or matched sustained title')
    prefix = f'native-planar-long-movie{movie_id}'
    stems = [f'{prefix}-{order}-flag{flag}' for order, flag in enumerate((0, 1, 1, 0), 1)]
    if {path.name for path in root.glob(f'{prefix}-*-flag?.json')} != {stem+'.json' for stem in stems}:
        raise ValueError('Exactly four expected sustained planar reports required')
    cases, original = [], None
    for order, (stem, flag) in enumerate(zip(stems, (0, 1, 1, 0)), 1):
        raw = json.loads((root/(stem+'.json')).read_text())
        if (raw.get('label') != stem or raw.get('media') != title or raw.get('movie_id') != movie_id or
                raw.get('seek_seconds') != 1200 or raw.get('requested_seconds') != 600 or
                raw.get('expected_route') != 'fp32'):
            raise ValueError('Wrong sustained source, label, scene, duration or reconstruction route')
        elapsed = raw.get('elapsed_seconds')
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 600:
            raise ValueError('Incomplete sustained observer duration')
        fixture = raw.get('subtitle_fixture')
        validate_fixture(fixture, movie_id)
        state = dict(enabled=fixture['before']['enabled'], index=fixture['before']['index'])
        if original is None:
            original = state
        elif state != original:
            raise ValueError('Original subtitle state differs across sustained cases')
        safe_fixture = {phase: dict(enabled=fixture[phase]['enabled'], index=fixture[phase]['index'])
                        for phase in ('before', 'disabled', 'disabled_at_end', 'restored')}
        safe_fixture['requested_enabled'] = False
        stopped = json.loads((root/(stem+'.json.stop.json')).read_text())
        qualification = validate_planar_report(raw, stopped, flag, binary_hash)
        cpu_elapsed = qualification['whole_process_cpu']['elapsed_seconds']
        if not math.isfinite(cpu_elapsed) or cpu_elapsed < 570:
            raise ValueError('Insufficient sustained CPU counter duration')
        journal = (root/(stem+'.journal.log')).read_text()
        kodi = (root/(stem+'.kodi.log')).read_text()
        shutdown = json.loads((root/(stem+'.shutdown.json')).read_text())
        if (CRASH.search(journal) or NATIVE_FAILURE.search(kodi) or
                'DVBridge native packed output failed' in kodi or
                'Deactivated successfully' not in journal or shutdown != SHUTDOWN):
            raise ValueError('Failed sustained process lifecycle or native rendering')
        if 'DVBridge output capture:' in kodi or 'DVBridge capture pair:' in kodi:
            raise ValueError('Readback during sustained performance case')
        summary = summarize(raw)
        health = summary['health']
        if (not health or not health['counter_window_valid'] or not health['normal_speed'] or
                not math.isfinite(health['source_seconds']) or health['source_seconds'] < 570):
            raise ValueError('Insufficient sustained source/health window')
        gpu = summary['gpu_counter_intervals']
        if gpu['valid_count'] < 2 or not math.isfinite(gpu['duration_seconds']) or gpu['duration_seconds'] < 570:
            raise ValueError('Insufficient sustained GPU counter duration')
        engines = [set(row['engine_busy_percent']) for row in raw['gpu_intervals'] if 'engine_busy_percent' in row]
        if (not engines or any(row != engines[0] for row in engines) or
                any(not math.isfinite(value) or value < 0 for value in gpu['time_weighted_busy_percent'].values())):
            raise ValueError('Invalid or inconsistent sustained GPU counters')
        cases.append(dict(order=order, packed_output_flag=flag, native_planar_flag=flag,
                          qualification=qualification, raw_health=raw_health_summary(raw),
                          health=health, gpu=gpu, stage=qualify_stage_window(raw, summary),
                          shutdown=shutdown, subtitle_fixture=safe_fixture,
                          display_restore_failure_observed='DVBridge: output restoration failed; retaining scanout state' in kodi))
    if any(set(row['gpu']['time_weighted_busy_percent']) != set(cases[0]['gpu']['time_weighted_busy_percent']) for row in cases):
        raise ValueError('GPU engine sets differ across sustained cases')
    pooled = {flag: pool(cases, flag) for flag in (0, 1)}
    for flag in (0, 1):
        rows = [row for row in cases if row['native_planar_flag'] == flag]
        counts = {key: sum(row['qualification']['packed_output']['interval_delta'][key] for row in rows)
                  for key in ('prepared', 'direct', 'composed')}
        counts['native_planar'] = sum(row['qualification']['native_planar']['preparation_count_delta'] for row in rows)
        counts['direct_preparation_percent'] = 100*counts['direct']/counts['prepared']
        counts['native_planar_preparation_percent'] = 100*counts['native_planar']/counts['prepared']
        pooled[flag]['renderer_preparation_routes'] = counts
    return dict(schema='yblod.native-planar-sustained-scalar-results.v1', content=title,
                movie_id=movie_id, seek_seconds=1200, seconds_per_case=600, matrix=[0, 1, 1, 0],
                same_installed_binary=True, binary_sha256=binary_hash, packed_output_enabled_in_both=True,
                before=pooled[0], after=pooled[1],
                cases=[{key: value for key, value in row.items() if key != 'packed_output_flag'} for row in cases],
                subtitle_fixture=dict(requested_enabled=False, original_state=original,
                    original_state_equal_across_cases=True, successful_disable_end_disabled_restore_cases=4,
                    original_preferences_restored_cases=4),
                lifecycle=dict(normal_process_exit_cases=4,
                    dv_display_restoration_failure_cases=sum(row['display_restore_failure_observed'] for row in cases),
                    successful_dv_display_restoration_claimed=False,
                    known_preexisting_issue='EGL surface destroyed before final DV restore'),
                scopes=[
                    'Fixed 600-second subtitle-free ABBA: exact candidate/title/seek1200; valid CPU, GPU and steady source windows each cover at least 570 seconds.',
                    'Only planar request differs; actual packed preparation must be 100% in both conditions, and actual planar preparations must exclusively match each flag.',
                    'All four subtitle fixtures prove disabled before/end and restored to the same original enabled/index state; visible subtitle composition is not measured.',
                    'GPU activity is deduplicated Kodi DRM counters weighted by actual durations; CPU is all Kodi threads normalized to one core.',
                    'Helper timings are released-operation-weighted cumulative-sum subtraction, not frame latency, tails or exclusive GPU time.',
                    'Raw startup/seek totals and steady drop/skip deltas are separate; observed stalls remain visible.',
                    'Process exit is distinct from display restoration; known preexisting restoration failures are explicitly reported.',
                    'Pixel preservation is separately qualified, not established by counters; no readback, private frames, hashes, paths or raw logs are published.'
                ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--movie-id', required=True, type=int)
    parser.add_argument('--expected-title', required=True)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.root, args.binary_sha256, args.movie_id, args.expected_title), indent=2, allow_nan=False))
