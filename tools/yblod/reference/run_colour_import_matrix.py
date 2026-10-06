"""Bounded FP32-only 0/1/1/0 colour-import playback test; no forced recovery."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from run_long_matrix import command, identity, wait_rpc
from observe_subtitle_fixture import validate_fixture

IMPORTS = {0: 'original-bl-el-reimport', 1: 'metadata-only'}
SCOPE = 'wrap-prepare-flush-destroy-excludes-native-release'
CRASH = re.compile(r'core dumped|dumped core|corrupted size|segfault|ABRT|Aborted|SIGABRT|'
                   r'Failed with result|Main process exited.*status=[1-9]|timed out|SIGKILL', re.I)
NATIVE_FAILURE = re.compile(r'fallback=release|cleanup retained|quarantine retained', re.I)


def fields(line):
    return dict(re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)', line))


def colour_handoff_summary(lines, flag, minimum_calls=240):
    expected = IMPORTS[flag]
    handoffs = [fields(line) for line in lines if 'DVBridge native colour handoff:' in line]
    presented = [fields(line) for line in lines if 'DVBridge native reconstruction:' in line
                 and 'presented=' in line]
    composers = [fields(line) for line in lines if 'DVBridge native composer:' in line]
    if not handoffs or not presented or not composers:
        raise ValueError('Missing colour, presentation or FP32 evidence')
    calls = []
    for entry in handoffs:
        required = {'calls', 'valid', 'imports', 'wall_ms_per_call', 'thread_cpu_ms_per_call', 'scope'}
        if (not required.issubset(entry) or entry['valid'] not in ('true', '1')
                or entry['imports'] != expected or entry['scope'] != SCOPE):
            raise ValueError('Invalid or wrong-route colour handoff')
        count = int(entry['calls'])
        if count <= 0 or any(not math.isfinite(float(entry[key])) or float(entry[key]) < 0
                            for key in ('wall_ms_per_call', 'thread_cpu_ms_per_call')):
            raise ValueError('Invalid colour call count or timing')
        calls.append(count)
    if len(calls) < 2 or any(b <= a for a, b in zip(calls, calls[1:])) or calls[-1] < minimum_calls:
        raise ValueError('Insufficient or reset colour timing counters')
    if any(entry.get('colour_imports') != expected for entry in presented):
        raise ValueError('Presented import route did not match requested route')
    if max(int(entry['presented']) for entry in presented) < 120:
        raise ValueError('Insufficient presented native operations')
    for entry in composers:
        if (entry.get('fp32_selected') != '1' or entry.get('accepted_integer') != '0'
                or entry.get('shader_compile_failed') != '0' or entry.get('generate_failed') != '0'):
            raise ValueError('FP32 route or shader generation qualification failed')
    if max(int(entry.get('accepted_fp32', '0')) for entry in composers) < minimum_calls:
        raise ValueError('Insufficient accepted FP32 operations')
    a, b = calls[0], calls[-1]
    metrics = {}
    for key in ('wall_ms_per_call', 'thread_cpu_ms_per_call'):
        delta = float(handoffs[-1][key]) * b - float(handoffs[0][key]) * a
        if delta < 0:
            raise ValueError('Colour cumulative timing regressed')
        metrics[key] = delta / (b - a)
    return {'flag': flag, 'imports': expected, 'first_calls': a, 'last_calls': b,
            'call_count_delta': b - a, 'weighted_window': metrics,
            'worst_case_log_rounding_error_ms': 0.0005 * (a + b) / (b - a),
            'scope': SCOPE, 'calls_are_not_unique_display_flips': True}


def process_cpu_summary(samples):
    if len(samples) < 2:
        raise ValueError('Missing whole-process CPU samples')
    required = ('pid', 'process_start_ticks', 'clock_ticks_per_second',
                'process_cpu_ticks', 'monotonic_ns')
    if any(not all(key in sample for key in required) for sample in samples):
        raise ValueError('Incomplete whole-process CPU samples')
    first, last = samples[0], samples[-1]
    if any((sample['pid'], sample['process_start_ticks'], sample['clock_ticks_per_second']) !=
           (first['pid'], first['process_start_ticks'], first['clock_ticks_per_second'])
           for sample in samples):
        raise ValueError('Kodi process CPU identity changed')
    if any(b['process_cpu_ticks'] < a['process_cpu_ticks'] or b['monotonic_ns'] <= a['monotonic_ns']
           for a, b in zip(samples, samples[1:])):
        raise ValueError('Process CPU samples regressed')
    clock = first['clock_ticks_per_second']
    if clock <= 0:
        raise ValueError('Invalid process CPU tick frequency')
    elapsed = (last['monotonic_ns'] - first['monotonic_ns']) / 1e9
    cpu = (last['process_cpu_ticks'] - first['process_cpu_ticks']) / clock
    return {'elapsed_seconds': elapsed, 'process_cpu_seconds': cpu,
            'average_percent_of_one_cpu': 100 * cpu / elapsed,
            'scope': 'Whole kodi.bin user+kernel process CPU, including other threads; '
                     'not engine-only CPU or GPU execution time.'}


def validate_report(report, after_stop, flag, expected_hash):
    if (report['failure_marker'] or report['log_rotated_or_truncated']
            or report['kodi_before'] != report['kodi_after']):
        raise ValueError('Observer or service identity qualification failed')
    for phase in ('runtime_before', 'runtime_after'):
        if report[phase]['binary_sha256'] != expected_hash:
            raise ValueError('Unexpected installed binary')
    if (after_stop['active_players'] or identity(after_stop['runtime']['service']) !=
            identity(report['runtime_after']['service']) or
            after_stop['runtime']['binary_sha256'] != expected_hash):
        raise ValueError('Player stop or binary/service identity changed')
    if any(NATIVE_FAILURE.search(line) for line in report['selected_log_lines']):
        raise ValueError('Native fallback or retained cleanup')
    return {'colour_handoff': colour_handoff_summary(report['selected_log_lines'], flag),
            'whole_process_cpu': process_cpu_summary(report['gpu_samples']),
            'observer_and_player_stop_integrity_passed': True}


def parser():
    result = argparse.ArgumentParser()
    result.add_argument('--binary-sha256', required=True)
    result.add_argument('--root', required=True, type=Path)
    result.add_argument('--observer', required=True, type=Path)
    result.add_argument('--config-dir', type=Path, default=Path(__file__).parent)
    result.add_argument('--movie-id', required=True, type=int)
    result.add_argument('--expected-title', required=True)
    result.add_argument('--seek-seconds', type=int, default=0)
    result.add_argument('--seconds', type=int, default=75)
    result.add_argument('--startup-settle-seconds', type=int, default=20)
    result.add_argument('--subtitles-off', action='store_true',
                        help='Matched subtitle-free fixture; observer restores original state before stop.')
    return result


def validate_args(args):
    validate_request(args)
    configs = [(args.config_dir / f'no-reimport-{flag}.conf').read_text() for flag in (0, 1)]
    validate_configs(configs)


def validate_request(args):
    if (not re.fullmatch(r'[a-f0-9]{64}', args.binary_sha256) or args.movie_id <= 0
            or not args.expected_title.strip() or not 0 <= args.seek_seconds <= 14400
            or not 75 <= args.seconds <= 900 or not 20 <= args.startup_settle_seconds <= 60):
        raise ValueError('Invalid bounded request')
    if not args.root.is_dir() or any(args.root.iterdir()) or not args.observer.is_file():
        raise ValueError('Fresh output directory and existing observer required')


def validate_configs(configs):
    normalized = []
    for flag, config in enumerate(configs):
        marker = f'Environment=DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT={flag}'
        if config.splitlines().count(marker) != 1:
            raise ValueError('Invalid colour-import configuration')
        for name in ('RECONSTRUCTION', 'DIAGNOSTICS', 'FP32'):
            if f'Environment=DVBRIDGE_NATIVE_{name}=1' not in config.splitlines():
                raise ValueError('Both cases require native FP32 and diagnostics')
        normalized.append('\n'.join(line for line in config.splitlines() if line != marker))
    if normalized[0] != normalized[1]:
        raise ValueError('Configurations differ beyond the colour-import flag')


def main():
    args = parser().parse_args()
    validate_args(args)
    run_configured_matrix(args,
        [args.config_dir / f'no-reimport-{flag}.conf' for flag in (0, 1)],
        'colour-imports', lambda flag: f'imports={IMPORTS[flag]}', validate_report)


def run_configured_matrix(args, configs, label_prefix, describe, report_validator,
                          observer_route=None):
    """Shared bounded lifecycle; caller validates its exact two configurations."""
    if (command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '--value').strip() != 'inactive'
            or command('systemctl', 'show', 'kodi', '-p', 'Result', '--value').strip() != 'success'):
        raise RuntimeError('Kodi must initially be cleanly stopped')
    override = Path('/run/systemd/system/kodi.service.d/yblod-native-playback.conf')
    original = override.read_bytes()
    completed = []
    try:
        for order, flag in enumerate((0, 1, 1, 0), 1):
            label = f'{label_prefix}-{order}-flag{flag}'
            shutil.copyfile(configs[flag], override)
            command('systemctl', 'daemon-reload')
            journal_start = int(time.time())
            command('systemctl', 'start', 'kodi')
            wait_rpc()
            before_settle = command('systemctl', 'show', 'kodi', '-p', 'MainPID',
                                    '-p', 'ActiveEnterTimestampMonotonic')
            time.sleep(args.startup_settle_seconds)
            wait_rpc()
            if before_settle != command('systemctl', 'show', 'kodi', '-p', 'MainPID',
                                        '-p', 'ActiveEnterTimestampMonotonic'):
                raise RuntimeError('Service changed during startup settling')
            if CRASH.search(command('journalctl', '-u', 'kodi', '--since', f'@{journal_start}', '--no-pager')):
                raise RuntimeError('Startup crash/failure marker')
            print(f'BEGIN {label} {describe(flag)}', flush=True)
            observer = ['/usr/bin/python3', str(args.observer), '--seconds', str(args.seconds),
                '--report', label + '.json', '--output-dir', str(args.root), '--label', label,
                '--expected-binary-sha256', args.binary_sha256, '--movie-id', str(args.movie_id),
                '--expected-title', args.expected_title, '--seek-seconds', str(args.seek_seconds),
                '--expected-route', observer_route(flag) if observer_route else 'fp32',
                '--stop-on-complete']
            if getattr(args, 'subtitles_off', False):
                observer.append('--subtitles-off')
            with (args.root / (label + '.observer.log')).open('x') as log:
                subprocess.run(observer, stdout=log, stderr=subprocess.STDOUT, check=True,
                               timeout=args.seconds + 100)
            report = json.loads((args.root / (label + '.json')).read_text())
            stopped = json.loads((args.root / (label + '.json.stop.json')).read_text())
            if getattr(args, 'subtitles_off', False):
                validate_fixture(report.get('subtitle_fixture'), args.movie_id)
            qualification = report_validator(report, stopped, flag, args.binary_sha256)
            if getattr(args, 'subtitles_off', False):
                qualification['subtitle_fixture'] = report['subtitle_fixture']
            (args.root / (label + '.qualification.json')).write_text(json.dumps(qualification, indent=2))
            command('systemctl', 'stop', 'kodi')
            status = dict(line.split('=', 1) for line in command('systemctl', 'show', 'kodi',
                '-p', 'Result', '-p', 'ActiveState', '-p', 'MainPID', '-p', 'ExecMainCode',
                '-p', 'ExecMainStatus').splitlines())
            shutil.copyfile('/storage/.kodi/temp/kodi.log', args.root / (label + '.kodi.log'))
            journal = command('journalctl', '-u', 'kodi', '--since', f'@{journal_start}', '--no-pager')
            (args.root / (label + '.journal.log')).write_text(journal)
            (args.root / (label + '.shutdown.json')).write_text(json.dumps(status))
            if (status.get('Result') != 'success' or status.get('ActiveState') != 'inactive'
                    or status.get('MainPID') != '0' or status.get('ExecMainCode') != '1'
                    or status.get('ExecMainStatus') != '0' or CRASH.search(journal)
                    or NATIVE_FAILURE.search((args.root / (label + '.kodi.log')).read_text())):
                raise RuntimeError('Unclean shutdown or retained/fallback native state')
            completed.append(label)
            print(f'PASS {label} observer/colour/player-stop/shutdown', flush=True)
        print(json.dumps({'status': 'complete', 'flags': [0, 1, 1, 0], 'completed': completed}), flush=True)
    finally:
        # Restore configuration only; never restart or force-kill a failed run.
        override.write_bytes(original)
        command('systemctl', 'daemon-reload')


if __name__ == '__main__':
    main()
