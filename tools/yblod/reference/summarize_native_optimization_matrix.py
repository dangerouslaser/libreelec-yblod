"""Strict scalar-only isolated-option planar SPR180 ABBA playback summary."""
import argparse
import json
import math
from pathlib import Path
import re

from run_colour_import_matrix import CRASH, NATIVE_FAILURE
from run_native_optimization_matrix import make_validator
from native_optimization_telemetry import qualify_actual_use
from native_optimization_qualification import OPTIONS, qualify_frames
from observe_subtitle_fixture import validate_fixture
from summarize_long_playback import summarize
from summarize_native_packed_matrix import SHUTDOWN, pool, qualify_stage_window, raw_health_summary


def service_memory(text):
    if not isinstance(text, str):
        raise ValueError('Missing service memory record')
    values = {}
    for line in text.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in ('MemoryCurrent', 'MemoryPeak', 'MemoryMax'):
            if key in values:
                raise ValueError('Duplicate service memory field')
            values[key] = value
    for key in ('MemoryCurrent', 'MemoryPeak'):
        if not re.fullmatch(r'[0-9]+', values.get(key, '')) or int(values[key]) <= 0:
            raise ValueError('Missing or invalid service memory bytes')
        values[key] = int(values[key])
    if values['MemoryPeak'] < values['MemoryCurrent']:
        raise ValueError('Service memory peak below current use')
    if 'MemoryMax' in values:
        limit = values['MemoryMax']
        if limit == 'infinity':
            values['MemoryMax'] = None
        elif re.fullmatch(r'[0-9]+', limit) and int(limit) > 0:
            values['MemoryMax'] = int(limit)
        else:
            raise ValueError('Invalid service memory limit')
    return values


def qualify_memory(raw):
    samples = raw.get('memory_samples')
    if not isinstance(samples, list) or len(samples) < 2:
        raise ValueError('Missing sampled service memory')
    rows = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('Malformed memory sample')
        stamp = sample.get('monotonic_ns')
        if type(stamp) is not int or stamp <= 0:
            raise ValueError('Invalid memory sample timestamp')
        memory = service_memory(sample.get('service'))
        if 'MemoryMax' not in memory:
            raise ValueError('Missing service memory limit')
        if rows and (stamp <= rows[-1][0] or memory['MemoryPeak'] < rows[-1][1]['MemoryPeak']):
            raise ValueError('Regressed memory sample timestamp or lifetime peak')
        rows.append((stamp, memory))
    limits = {memory['MemoryMax'] for _, memory in rows}
    duration = (rows[-1][0] - rows[0][0]) / 1e9
    if duration < 150 or len(limits) != 1:
        raise ValueError('Insufficient or changed service memory observation')
    weighted = sum((b[0]-a[0])*a[1]['MemoryCurrent'] for a, b in zip(rows, rows[1:]))
    snapshots = {phase: service_memory(raw.get(phase, {}).get('service'))
                 for phase in ('runtime_before', 'runtime_after')}
    return dict(sample_count=len(rows), elapsed_seconds=duration,
                service_current_time_weighted_bytes=weighted/(rows[-1][0]-rows[0][0]),
                service_current_min_bytes=min(memory['MemoryCurrent'] for _, memory in rows),
                service_current_max_bytes=max(memory['MemoryCurrent'] for _, memory in rows),
                service_lifetime_peak_bytes=max(memory['MemoryPeak'] for _, memory in rows),
                service_memory_limit_bytes=next(iter(limits)), snapshots=snapshots,
                process_rss_available=False)


def pool_memory(rows):
    limits = {row['memory']['service_memory_limit_bytes'] for row in rows}
    if len(limits) != 1:
        raise ValueError('Memory limits differ across matched cases')
    elapsed = sum(row['memory']['elapsed_seconds'] for row in rows)
    return dict(sampled_elapsed_seconds=elapsed,
                service_current_time_weighted_bytes=sum(row['memory']['elapsed_seconds']*
                    row['memory']['service_current_time_weighted_bytes'] for row in rows)/elapsed,
                service_current_min_bytes=min(row['memory']['service_current_min_bytes'] for row in rows),
                service_current_max_bytes=max(row['memory']['service_current_max_bytes'] for row in rows),
                service_lifetime_peak_bytes=max(row['memory']['service_lifetime_peak_bytes'] for row in rows),
                service_memory_limit_bytes=next(iter(limits)), process_rss_available=False)


def aggregate(root, binary_hash, option, preservation_reports):
    if option not in OPTIONS or not preservation_reports:
        raise ValueError("Exact same-candidate proof and isolated option required")
    proof = [qualify_frames(path, binary_hash, option) for path in preservation_reports]
    validator = make_validator(option, qualify_actual_use)
    if not re.fullmatch(r'[a-f0-9]{64}', binary_hash):
        raise ValueError('Invalid candidate binary hash')
    stems = [f'native-optimization-{option}-{order}-flag{flag}' for order, flag in enumerate((0, 1, 1, 0), 1)]
    if {path.name for path in root.glob(f'native-optimization-{option}-*-flag?.json')} != {stem+'.json' for stem in stems}:
        raise ValueError('Exactly four expected planar ABBA reports required')
    cases = []
    original_subtitle_state = None
    for order, (stem, flag) in enumerate(zip(stems, (0, 1, 1, 0)), 1):
        raw = json.loads((root/(stem+'.json')).read_text())
        if (raw.get('label') != stem or raw.get('media') != 'Saving Private Ryan' or
                raw.get('movie_id') != 3391 or raw.get('seek_seconds') != 1200 or
                raw.get('requested_seconds') != 180 or raw.get('expected_route') != 'fp32'):
            raise ValueError('Wrong planar case label, source, scene, duration or reconstruction route')
        elapsed = raw.get('elapsed_seconds')
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 180:
            raise ValueError('Incomplete requested planar observation duration')
        fixture = raw.get('subtitle_fixture')
        validate_fixture(fixture, 3391)
        before = dict(enabled=fixture['before']['enabled'], index=fixture['before'].get('index'))
        if original_subtitle_state is None:
            original_subtitle_state = before
        elif before != original_subtitle_state:
            raise ValueError('Original subtitle enabled/index state differs across planar cases')
        safe_fixture = {phase: dict(enabled=fixture[phase]['enabled'], index=fixture[phase].get('index'))
                        for phase in ('before', 'disabled', 'disabled_at_end', 'restored')}
        safe_fixture['requested_enabled'] = False
        stopped = json.loads((root/(stem+'.json.stop.json')).read_text())
        qualification = validator(raw, stopped, flag, binary_hash)
        if qualification['whole_process_cpu']['elapsed_seconds'] < 150:
            raise ValueError('Insufficient process CPU observation window')
        journal = (root/(stem+'.journal.log')).read_text()
        kodi = (root/(stem+'.kodi.log')).read_text()
        shutdown = json.loads((root/(stem+'.shutdown.json')).read_text())
        if (CRASH.search(journal) or NATIVE_FAILURE.search(kodi) or
                'DVBridge native packed output failed' in kodi or
                'Deactivated successfully' not in journal or shutdown != SHUTDOWN):
            raise ValueError('Incomplete or failed planar process lifecycle qualification')
        if 'DVBridge output capture:' in kodi or 'DVBridge capture pair:' in kodi:
            raise ValueError('Readback capture occurred during planar performance measurement')
        summary = summarize(raw)
        health = summary['health']
        if (not health or not health['counter_window_valid'] or not health['normal_speed'] or
                health['source_seconds'] < 150):
            raise ValueError('Missing or insufficient steady planar playback-health window')
        gpu = summary['gpu_counter_intervals']
        if gpu['valid_count'] < 2 or not math.isfinite(gpu['duration_seconds']) or gpu['duration_seconds'] < 150:
            raise ValueError('Missing GPU counter observations')
        engine_sets = [set(row['engine_busy_percent']) for row in raw['gpu_intervals']
                       if 'engine_busy_percent' in row]
        if not engine_sets or any(row != engine_sets[0] for row in engine_sets):
            raise ValueError('GPU engine sets changed within a planar case')
        if any(not math.isfinite(value) or value < 0 for value in gpu['time_weighted_busy_percent'].values()):
            raise ValueError('Invalid planar GPU busy metrics')
        cases.append(dict(order=order, packed_output_flag=flag, native_planar_flag=1, optimization_flag=flag,
                          qualification=qualification, raw_health=raw_health_summary(raw),
                          health=health, stage=qualify_stage_window(raw, summary), gpu=gpu,
                          memory=qualify_memory(raw),
                          shutdown=shutdown,
                          subtitle_fixture=safe_fixture,
                          display_restore_failure_observed='DVBridge: output restoration failed; retaining scanout state' in kodi))
    if any(set(row['gpu']['time_weighted_busy_percent']) !=
           set(cases[0]['gpu']['time_weighted_busy_percent']) for row in cases):
        raise ValueError('GPU engine sets differ across the planar matrix')
    pooled = {flag: pool(cases, flag) for flag in (0, 1)}
    for flag in (0, 1):
        rows = [row for row in cases if row['optimization_flag'] == flag]
        counts = {key: sum(row['qualification']['packed_output']['interval_delta'][key] for row in rows)
                  for key in ('prepared', 'direct', 'composed')}
        counts['native_planar'] = sum(row['qualification']['native_planar']['preparation_count_delta'] for row in rows)
        counts['direct_preparation_percent'] = 100*counts['direct']/counts['prepared']
        counts['native_planar_preparation_percent'] = 100*counts['native_planar']/counts['prepared']
        pooled[flag]['renderer_preparation_routes'] = counts
        pooled[flag]['memory'] = pool_memory(rows)
    if pooled[0]['memory']['service_memory_limit_bytes'] != pooled[1]['memory']['service_memory_limit_bytes']:
        raise ValueError('Memory limits differ between optimization conditions')
    return dict(schema='yblod.native-optimization-playback-scalar-results.v1',
                optimization=option, output_preservation_qualified=proof,
                content='Saving Private Ryan', movie_id=3391, seek_seconds=1200,
                seconds_per_case=180, matrix=[0, 1, 1, 0], same_installed_binary=True,
                binary_sha256=binary_hash, packed_output_enabled_in_both=True, native_planar_enabled_in_both=True,
                subtitle_fixture=dict(requested_enabled=False,
                    original_state=original_subtitle_state, original_state_equal_across_cases=True,
                    successful_disable_end_disabled_restore_cases=4,
                    original_preferences_restored_cases=4),
                before=pooled[0], after=pooled[1],
                cases=[{key: value for key, value in row.items() if key != 'packed_output_flag'} for row in cases],
                lifecycle=dict(normal_process_exit_cases=4,
                    dv_display_restoration_failure_cases=sum(row['display_restore_failure_observed'] for row in cases),
                    successful_dv_display_restoration_claimed=False,
                    known_preexisting_issue='EGL surface destroyed before final DV restore'),
                scopes=[
                    'Only selected optimization differs, with the other optimization disabled and planar output enabled in both; native FP32/LUT, metadata-only handoff, release-RGB math and packed output remain enabled in both conditions.',
                    'Subtitle-free benchmark fixture: all four cases prove subtitles disabled before and at the end of measurement, then restored to the same original enabled/index state; this does not measure visible subtitle composition.',
                    'Actual successful native-planar and direct-packed routes are exclusive in both; selected-option execution counters must match successful accepted operations; failures or legacy fallback are rejected.',
                    'GPU is deduplicated Kodi DRM client activity weighted by actual interval durations, not exclusive shader time.',
                    'CPU is all Kodi threads normalized to one CPU core and independently weighted by actual process observation durations.',
                    'Memory is whole-service sampled MemoryCurrent with left-held time weighting, not process RSS or engine/GPU allocations; sampled extrema can miss between-sample peaks. MemoryPeak is service lifetime high-water, not interval-only use. Before/after-observation snapshots are reported separately from the sampled measurement window.',
                    'Helper wall timings are cumulative-sum subtraction weighted by released operations, not frame latency or unique HDMI flips.',
                    'Raw startup/seek totals and steady-window drop/skip deltas are separate; stalls remain visible.',
                    'Same-candidate exact frame preservation proof is required before aggregation; playback counters do not establish pixel accuracy.',
                    'Normal process exit does not prove successful DV display restoration; the known preexisting lifecycle issue is reported separately.',
                    'No readback captures, raw logs, private frame/metadata hashes or private source paths are published.'
                ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--optimization', required=True, choices=OPTIONS)
    parser.add_argument('--preservation-report', action='append', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.root, args.binary_sha256, args.optimization, args.preservation_report), indent=2, allow_nan=False))
