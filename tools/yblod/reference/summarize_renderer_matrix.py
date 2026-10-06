"""Sanitize the completed retained-renderer/current-engine comparison."""
import argparse
import json
from pathlib import Path
from run_renderer_matrix import validate_renderer_report
from run_colour_import_matrix import CRASH, NATIVE_FAILURE
from summarize_long_playback import summarize


def aggregate(root, binary_hash):
    cases = []
    for order, flag in enumerate((0, 1, 1, 0), 1):
        stem = f'renderer-{order}-flag{flag}'
        raw = json.loads((root / (stem + '.json')).read_text())
        stopped = json.loads((root / (stem + '.json.stop.json')).read_text())
        qualification = validate_renderer_report(raw, stopped, flag, binary_hash)
        journal = (root / (stem + '.journal.log')).read_text()
        kodi = (root / (stem + '.kodi.log')).read_text()
        shutdown = json.loads((root / (stem + '.shutdown.json')).read_text())
        if (CRASH.search(journal) or NATIVE_FAILURE.search(kodi) or
            'Deactivated successfully' not in journal or
            shutdown != dict(ActiveState='inactive', MainPID='0', Result='success',
                             ExecMainCode='1', ExecMainStatus='0')):
            raise ValueError('Incomplete or failed lifecycle qualification')
        summary = summarize(raw)
        cases.append(dict(order=order, native_flag=flag, qualification=qualification,
            health=summary['health'], stage=summary['stage_window'],
            gpu=summary['gpu_counter_intervals'], memory=summary['memory_snapshots'],
            shutdown=shutdown, actual_conversions=[line.split('DVBridge conversion:', 1)[1].strip()
                for line in raw['route_log_lines'] if 'DVBridge conversion:' in line]))
    pooled = {}
    for flag in (0, 1):
        rows = [row for row in cases if row['native_flag'] == flag]
        cpu = sum(row['qualification']['whole_process_cpu']['process_cpu_seconds'] for row in rows)
        elapsed = sum(row['qualification']['whole_process_cpu']['elapsed_seconds'] for row in rows)
        gpu_elapsed = sum(row['gpu']['duration_seconds'] for row in rows)
        engines = sorted(rows[0]['gpu']['time_weighted_busy_percent'])
        pooled[str(flag)] = dict(whole_kodi_cpu_percent_one_core=100*cpu/elapsed,
            gpu_engine_busy_percent={engine: sum(row['gpu']['duration_seconds'] *
                row['gpu']['time_weighted_busy_percent'][engine] for row in rows)/gpu_elapsed
                for engine in engines})
    return dict(schema='yblod.retained-renderer-comparison.v1', date='2026-10-06',
        content='Saving Private Ryan', seek_seconds=1200, seconds_per_case=180,
        matrix=[0, 1, 1, 0], same_installed_binary=True, binary_sha256=binary_hash,
        before=pooled['0'], after=pooled['1'], cases=cases,
        scopes=['Retained earlier renderer in this binary, not a pristine upstream or historic release build.',
            'GPU counters are time-weighted deduplicated Kodi client activity, not isolated shader time.',
            'CPU includes all Kodi threads and uses one-core normalization.',
            'Both conditions retain the same output settings but use different actual conversion/packing routes.',
            'Playback counters do not establish pixel quality or Dolby conformance.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--binary-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.root, args.binary_sha256), indent=2, allow_nan=False))
