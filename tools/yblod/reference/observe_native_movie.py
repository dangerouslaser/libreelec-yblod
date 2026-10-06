"""Private bounded playback observer; no film pixels or metadata extraction."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path('/storage/yblod-native-playback-20261006')
LOG = Path('/storage/.kodi/temp/kodi.log')
parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=75)
parser.add_argument('--report', default='1917-owned-source-observation.json')
parser.add_argument('--stop-on-complete', action='store_true')
parser.add_argument('--output-dir', default=str(ROOT))
parser.add_argument('--label', required=True)
parser.add_argument('--expected-binary-sha256', required=True)
parser.add_argument('--movie-id', type=int, required=True)
parser.add_argument('--expected-title', required=True)
parser.add_argument('--seek-seconds', type=int, default=0)
parser.add_argument('--expected-route', choices=('integer', 'fp32'), required=True)
args = parser.parse_args()
if (not 5 <= args.seconds <= 1800 or Path(args.report).name != args.report
        or args.movie_id <= 0 or not 0 <= args.seek_seconds <= 14400
        or not args.expected_title.strip()):
    raise SystemExit('Invalid bounded observation request')
if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', args.label):
    raise SystemExit('Invalid run label')
if not re.fullmatch(r'[a-f0-9]{64}', args.expected_binary_sha256):
    raise SystemExit('Invalid binary SHA256')
ROOT = Path(args.output_dir)
if not ROOT.is_dir() or (ROOT / args.report).exists():
    raise SystemExit('Output directory missing or report already exists')

def runtime_snapshot():
    digest = hashlib.sha256()
    with Path('/usr/lib/kodi/kodi.bin').open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    identity = subprocess.check_output(
        ['systemctl', 'show', 'kodi', '-p', 'MainPID', '-p', 'ActiveEnterTimestampMonotonic',
         '-p', 'ActiveState', '-p', 'MemoryCurrent', '-p', 'MemoryPeak'], text=True)
    connectors = {str(path): path.read_text().strip()
                  for path in Path('/sys/class/drm').glob('card*-*/status')}
    return {'binary_sha256': digest.hexdigest(), 'service': identity,
            'connector_status': connectors}

def rpc(method, params=None):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method,
                       'params': params or {}}).encode()
    request = urllib.request.Request('http://127.0.0.1:8080/jsonrpc', body,
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result.get('result')

def gpu_snapshot():
    """Read deduplicated process-client counters; never normalize by frequency."""
    snapshot = {'monotonic_ns': time.monotonic_ns(), 'clients': {}, 'frequencies': {}}
    pids = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / 'comm').read_text().strip() != 'kodi.bin':
                continue
            snapshot['pid'] = int(proc.name)
            pids.append(int(proc.name))
            for fd in (proc / 'fdinfo').iterdir():
                fields = {}
                for line in fd.read_text().splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        fields[key] = value.strip()
                if 'drm-client-id' not in fields or 'drm-pdev' not in fields:
                    continue
                key = fields['drm-pdev'] + '/' + fields['drm-client-id']
                counters = {}
                for name, value in fields.items():
                    if re.fullmatch(r'drm-engine-(?:render|copy|video|video-enhance|compute)', name):
                        if not re.fullmatch(r'\d+ ns', value):
                            snapshot['error'] = 'invalid counter units'
                            continue
                        counters[name] = int(value.split()[0])
                    elif name.startswith('drm-engine-capacity-'):
                        if not re.fullmatch(r'\d+', value):
                            snapshot['error'] = 'invalid capacity'
                            continue
                        counters[name] = int(value)
                snapshot['clients'][key] = counters
        except (OSError, ValueError):
            continue
    if len(pids) != 1 or not snapshot['clients']:
        snapshot['error'] = 'missing or ambiguous Kodi process/client'
    for path in Path('/sys/class/drm/card0').glob('gt_*freq_mhz'):
        try:
            snapshot['frequencies'][path.name] = int(path.read_text())
        except (OSError, ValueError):
            pass
    return snapshot

def gpu_interval(before, after):
    elapsed = after['monotonic_ns'] - before['monotonic_ns']
    if before.get('error') or after.get('error'):
        return {'unavailable': before.get('error') or after.get('error')}
    if before.get('pid') != after.get('pid') or elapsed <= 0:
        return {'unavailable': 'process changed or invalid elapsed time'}
    if set(before['clients']) != set(after['clients']):
        return {'unavailable': 'DRM client set changed'}
    totals, capacities = {}, {}
    for key, start in before['clients'].items():
        end = after['clients'][key]
        if set(start) != set(end):
            return {'unavailable': 'engine counter set changed'}
        for name, value in start.items():
            if name.startswith('drm-engine-capacity-'):
                continue
            if name not in end or end[name] < value:
                return {'unavailable': 'counter missing or regressed'}
            capacity_name = name.replace('drm-engine-', 'drm-engine-capacity-')
            capacity = start.get(capacity_name, 1)
            if end.get(capacity_name, 1) != capacity or capacity <= 0:
                return {'unavailable': 'engine capacity changed'}
            if name in capacities and capacities[name] != capacity:
                return {'unavailable': 'inconsistent engine capacities'}
            capacities[name] = capacity
            totals[name] = totals.get(name, 0) + end[name] - value
    return {'elapsed_seconds': elapsed / 1e9,
            'engine_busy_percent': {k: 100 * v / elapsed / capacities[k]
                                    for k, v in totals.items()},
            'capacity': capacities}

if rpc('Player.GetActivePlayers'):
    raise RuntimeError('A player is already active; refusing to replace it')
movie = rpc('VideoLibrary.GetMovieDetails', {'movieid': args.movie_id,
                                           'properties': ['title', 'runtime']})['moviedetails']
if movie.get('title') != args.expected_title:
    raise RuntimeError('Movie ID/title mismatch; refusing playback')
if args.seek_seconds and movie.get('runtime', 0) <= args.seek_seconds:
    raise RuntimeError('Seek point exceeds known movie runtime')
runtime_before = runtime_snapshot()
if runtime_before['binary_sha256'] != args.expected_binary_sha256:
    raise RuntimeError('Unexpected Kodi binary; refusing playback')
if 'connected' not in runtime_before['connector_status'].values():
    raise RuntimeError('No connected display; refusing headless playback comparison')
identity = subprocess.check_output(
    ['systemctl', 'show', 'kodi', '-p', 'MainPID', '-p', 'ActiveEnterTimestampMonotonic'],
    text=True)
position = LOG.stat().st_size
log_inode = LOG.stat().st_ino
rpc('Player.Open', {'item': {'movieid': args.movie_id}, 'options': {'resume': False}})
if args.seek_seconds:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        active = [p for p in rpc('Player.GetActivePlayers') if p['type'] == 'video']
        if len(active) == 1:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Video player did not become active for seek')
    seconds = args.seek_seconds
    rpc('Player.Seek', {'playerid': active[0]['playerid'], 'value': {'time': {
        'hours': seconds // 3600, 'minutes': seconds // 60 % 60,
        'seconds': seconds % 60, 'milliseconds': 0}}})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        props = rpc('Player.GetProperties', {'playerid': active[0]['playerid'],
                                             'properties': ['time', 'speed']})
        clock = props['time']
        actual = clock['hours'] * 3600 + clock['minutes'] * 60 + clock['seconds']
        if abs(actual - seconds) <= 3 and props['speed'] == 1:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Seek did not reach requested source window')
    # Exclude pre-seek diagnostic totals from the requested window.
    status = LOG.stat()
    if status.st_ino != log_inode or status.st_size < position:
        raise RuntimeError('Log changed while seeking')
    position = status.st_size
print(f'{args.expected_title} playback requested at {args.seek_seconds}s; '
      f'observing up to {args.seconds} seconds', flush=True)
started = time.monotonic()
started_ns = time.monotonic_ns()
lines = []
failed = False
failure_reasons = []
gpu_samples = []
player_samples = []
memory_samples = []
partial_line = b''
log_changed = False
while time.monotonic() - started < args.seconds:
    time.sleep(2)
    gpu_samples.append(gpu_snapshot())
    if not memory_samples or time.monotonic_ns() - memory_samples[-1]['monotonic_ns'] >= 10_000_000_000:
        memory_samples.append({'monotonic_ns': time.monotonic_ns(),
            'service': subprocess.check_output(['systemctl', 'show', 'kodi',
                '-p', 'MemoryCurrent', '-p', 'MemoryPeak', '-p', 'MemoryMax'], text=True),
            'meminfo': {key: value.strip() for key, value in
                (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
                if key in ('MemAvailable', 'SwapTotal', 'SwapFree')}})
    try:
        active = [p for p in rpc('Player.GetActivePlayers') if p['type'] == 'video']
        if len(active) != 1:
            failed = True
            failure_reasons.append('video player stopped or became ambiguous')
        else:
            player_samples.append({'monotonic_ns': time.monotonic_ns(), 'properties': rpc(
                'Player.GetProperties', {'playerid': active[0]['playerid'],
                                        'properties': ['time', 'speed', 'percentage']})})
    except (OSError, RuntimeError, ValueError):
        failed = True
        failure_reasons.append('player JSON-RPC became unavailable')
    # Read the final log interval even if the player disappeared.
    status = LOG.stat()
    if status.st_ino != log_inode or status.st_size < position:
        log_changed = True
        failed = True
        break
    with LOG.open('rb') as handle:
        handle.seek(position)
        chunk = handle.read()
        position = handle.tell()
    complete_lines = (partial_line + chunk).split(b'\n')
    partial_line = complete_lines.pop()
    for raw_line in complete_lines:
        line = raw_line.decode(errors='replace')
        if 'DVBridge' in line and any(marker in line for marker in
                ('fallback=release', 'cleanup retained', 'quarantine retained')):
            failed = True
            if line not in lines:
                lines.append(line)
                print(line, flush=True)
        if any(marker in line for marker in (
            'DVBridge native reconstruction:', 'DVBridge playback health:', 'DVBridge native timing:',
            'DVBridge native composer:',
            'DVBridge stream candidate:', 'DVBridge first frame:')):
            lines.append(line)
            print(line, flush=True)
            if 'fallback=release' in line or 'cleanup retained' in line:
                failed = True
            if 'DVBridge native composer:' in line:
                counters = {key: int(value) for key, value in re.findall(
                    r'(fp32_selected|accepted_fp32|accepted_integer|shader_compile_failed|generate_failed)=(\d+)', line)}
                selected = 1 if args.expected_route == 'fp32' else 0
                required = {'fp32_selected', 'accepted_fp32', 'accepted_integer',
                            'shader_compile_failed', 'generate_failed'}
                if (not required.issubset(counters)
                        or counters.get('fp32_selected') != selected
                        or counters.get('shader_compile_failed', 0)
                        or counters.get('generate_failed', 0)
                        or counters.get('accepted_integer' if selected else 'accepted_fp32', 0)):
                    failed = True
    if failed:
        break
after = subprocess.check_output(
    ['systemctl', 'show', 'kodi', '-p', 'MainPID', '-p', 'ActiveEnterTimestampMonotonic'],
    text=True)
runtime_after = runtime_snapshot()
if identity != after or runtime_after['binary_sha256'] != args.expected_binary_sha256:
    failed = True
if not any('DVBridge native composer:' in line for line in lines):
    failed = True
report = {'media': args.expected_title, 'movie_id': args.movie_id,
          'requested_seconds': args.seconds, 'seek_seconds': args.seek_seconds,
          'expected_route': args.expected_route,
          'player_samples': player_samples,
          'memory_samples': memory_samples,
          'scope': 'Kodi commit/health markers, not HDMI flips or colour accuracy',
          'observer_started_monotonic_ns': started_ns,
          'elapsed_seconds': time.monotonic() - started, 'kodi_before': identity,
          'kodi_after': after, 'failure_marker': failed, 'selected_log_lines': lines,
          'failure_reasons': failure_reasons,
          'log_rotated_or_truncated': log_changed,
          'gpu_samples': gpu_samples,
          'gpu_intervals': [gpu_interval(a, b) for a, b in zip(gpu_samples, gpu_samples[1:])]}
report.update({'label': args.label, 'runtime_before': runtime_before,
               'runtime_after': runtime_after})
with (ROOT / args.report).open('x') as handle:
    handle.write(json.dumps(report, indent=2) + '\n')
print(json.dumps({'observation_complete': True, 'failure_marker': failed,
                  'service_identity_unchanged': identity == after}), flush=True)
if args.stop_on_complete and not failed and identity == after:
    for player in rpc('Player.GetActivePlayers'):
        if player['type'] == 'video':
            rpc('Player.Stop', {'playerid': player['playerid']})
    print('Completed observation; playback stop requested', flush=True)
    # Stop is not service shutdown. Inspect its aftermath without restarting Kodi.
    time.sleep(3)
    report['after_stop'] = {'active_players': rpc('Player.GetActivePlayers'),
                            'runtime': runtime_snapshot()}
    with (ROOT / (args.report + '.stop.json')).open('x') as handle:
        handle.write(json.dumps(report['after_stop'], indent=2) + '\n')
# Failure/quarantine stop/restart decisions remain with the controller.
