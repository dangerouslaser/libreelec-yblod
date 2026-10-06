"""Private bounded scene capture; readback runs are not performance tests."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


def rpc(method, params=None):
    data = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params or {})).encode()
    request = urllib.request.Request('http://127.0.0.1:8080/jsonrpc', data,
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result['result']


def command(*args):
    return subprocess.check_output(args, text=True, timeout=45)


def process_identity():
    service_pid = int(command('systemctl', 'show', 'kodi', '-p', 'MainPID', '--value').strip())
    if service_pid <= 0:
        raise RuntimeError('No Kodi service process')
    matches = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if (proc / 'comm').read_text().strip() != 'kodi.bin':
                continue
            fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[1]) == service_pid:
                matches.append((proc, int(fields[19])))
        except FileNotFoundError:
            continue
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one kodi.bin child of the Kodi service process')
    proc, start_ticks = matches[0]
    digest = hashlib.sha256()
    with (proc / 'exe').open('rb') as binary:
        for block in iter(lambda: binary.read(1024 * 1024), b''):
            digest.update(block)
    return dict(service_pid=service_pid, pid=int(proc.name), start_ticks=start_ticks,
                binary_sha256=digest.hexdigest())


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--binary-sha256', help='Expected installed Kodi executable digest; always recorded.')
    parser.add_argument('--expected-native', type=int, choices=(0, 1))
    parser.add_argument('--expected-direct-packed', type=int, choices=(0, 1))
    parser.add_argument('--expected-native-planar', type=int, choices=(0, 1))
    media = parser.add_mutually_exclusive_group()
    media.add_argument('--movie-id', type=int, default=3391)
    media.add_argument('--file', help='Absolute local media path for a clip outside the movie library.')
    parser.add_argument('--expected-title', default='Saving Private Ryan')
    parser.add_argument('--seek-seconds', type=float, default=1200)
    parser.add_argument('--target-seconds', type=float, action='append',
                        help='Absolute movie time to capture; repeat up to three times. Defaults to seek plus 10/20/30 seconds.')
    args = parser.parse_args(argv)
    if args.movie_id <= 0 or not args.expected_title.strip():
        parser.error('Positive movie ID and nonempty expected title required')
    if args.file is not None and not Path(args.file).is_absolute():
        parser.error('An absolute local media file path is required')
    if not math.isfinite(args.seek_seconds) or not 0 <= args.seek_seconds <= 86400:
        parser.error('Seek must be finite and between zero and 86400 seconds')
    if args.baseline and args.target_seconds:
        parser.error('Explicit target times cannot be combined with an exact-frame baseline')
    if not args.baseline:
        args.target_seconds = args.target_seconds or [args.seek_seconds + offset for offset in (10, 20, 30)]
        if not 1 <= len(args.target_seconds) <= 3 or any(
                not math.isfinite(value) or not args.seek_seconds < value <= 86400 for value in args.target_seconds):
            parser.error('One to three finite target times after the seek and at most 86400 seconds required')
        if args.target_seconds != sorted(set(args.target_seconds)):
            parser.error('Target times must be strictly increasing')
    return args


def open_item(args):
    return {'file': args.file} if args.file else {'movieid': args.movie_id}


def verify_file_item(args, player):
    if args.file:
        item = rpc('Player.GetItem', {'playerid': player, 'properties': ['file']})['item']
        if item.get('file') != args.file:
            raise RuntimeError('Unexpected playing file identity')


def verify_capture_route(info, args):
    for field, expected in (('native', args.expected_native),
                            ('direct_packed', args.expected_direct_packed),
                            ('native_planar', args.expected_native_planar)):
        if expected is not None and (type(info.get(field)) is not int or info.get(field) != expected):
            raise RuntimeError('Wrong captured rendering route: ' + field)


def capture_targets(args):
    if not args.baseline:
        return [(seconds * 1000000, 0) for seconds in args.target_seconds]
    frames = json.loads(args.baseline.read_text())['frames']
    values = [row['pts'] for row in frames]
    if not 1 <= len(values) <= 3 or any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not args.seek_seconds * 1000000 < value <= 86400000000 for value in values):
        raise RuntimeError('Invalid exact-frame baseline targets')
    if values != sorted(set(values)):
        raise RuntimeError('Exact-frame baseline targets must be strictly increasing')
    return [(value, 1) for value in values]


def main():
    args = parse_args()
    if command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '--value').strip() != 'inactive':
        raise RuntimeError('Kodi must be inactive before capture')
    root = Path('/storage/dvbridge-output-captures')
    root.mkdir(exist_ok=True)
    request = root / 'request'
    if request.exists() or args.report.exists():
        raise RuntimeError('Fresh request/report required')
    targets = capture_targets(args)
    override = Path('/run/systemd/system/kodi.service.d/yblod-native-playback.conf')
    shutil.copyfile(args.config, override)
    command('systemctl', 'daemon-reload')
    command('systemctl', 'start', 'kodi')
    for _ in range(30):
        try:
            if rpc('Player.GetActivePlayers') == []:
                break
        except (OSError, RuntimeError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError('Kodi not reachable and idle')
    time.sleep(20)
    identity = process_identity()
    if args.binary_sha256 and identity['binary_sha256'] != args.binary_sha256.lower():
        raise RuntimeError('Wrong Kodi binary')
    title = None
    if not args.file:
        title = rpc('VideoLibrary.GetMovieDetails', {'movieid': args.movie_id, 'properties': ['title']})['moviedetails']['title']
        if title != args.expected_title:
            raise RuntimeError('Unexpected movie identity')
    existing = set(root.glob('frame-*'))
    request.write_text(f'{targets[0][0]:.17g} {targets[0][1]}\n')
    rpc('Player.Open', {'item': open_item(args), 'options': {'resume': False}})
    player = None
    for _ in range(30):
        players = rpc('Player.GetActivePlayers')
        if players:
            player = players[0]['playerid']
            break
        time.sleep(1)
    if player is None:
        raise RuntimeError('No player')
    verify_file_item(args, player)
    milliseconds = round(args.seek_seconds * 1000)
    rpc('Player.Seek', {'playerid': player, 'value': {'time': {'hours': milliseconds // 3600000,
                       'minutes': milliseconds // 60000 % 60, 'seconds': milliseconds // 1000 % 60,
                       'milliseconds': milliseconds % 1000}}})
    captured = []
    for index, (pts, exact) in enumerate(targets):
        if index:
            request.write_text(f'{pts:.17g} {exact}\n')
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            new = set(root.glob('frame-*')) - existing
            ready = [path for path in new if (path / 'frame.json').is_file()]
            if len(ready) == 1:
                path = ready[0]
                info = json.loads((path / 'frame.json').read_text())
                if exact and abs(info['pts'] - pts) > 1:
                    raise RuntimeError('Wrong exact source frame')
                verify_capture_route(info, args)
                info['directory'] = str(path)
                captured.append(info)
                existing.add(path)
                print(json.dumps(info), flush=True)
                break
            if new and not request.exists():
                time.sleep(1)
                if not any((path / 'frame.json').is_file() for path in new):
                    raise RuntimeError('Failed capture; inspect Kodi log')
            time.sleep(.1)
        else:
            raise RuntimeError('Capture timed out')
    rpc('Player.Stop', {'playerid': player})
    time.sleep(2)
    if rpc('Player.GetActivePlayers'):
        raise RuntimeError('Player did not stop')
    final_identity = process_identity()
    if final_identity != identity:
        raise RuntimeError('Kodi service process or executable changed during capture')
    command('systemctl', 'stop', 'kodi')
    state = command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '-p', 'Result', '-p', 'MainPID')
    if set(state.splitlines()) != {'ActiveState=inactive', 'Result=success', 'MainPID=0'}:
        raise RuntimeError(state)
    report = dict(frames=captured, shutdown=state, identity_before=identity, identity_after=final_identity)
    if args.file:
        report['file'] = dict(basename=Path(args.file).name, seek_seconds=args.seek_seconds)
    else:
        report['movie'] = dict(id=args.movie_id, title=title, seek_seconds=args.seek_seconds)
    args.report.write_text(json.dumps(report, indent=2))
    print('PASS capture/player-stop/shutdown', flush=True)


if __name__ == '__main__':
    main()
