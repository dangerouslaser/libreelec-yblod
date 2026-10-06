"""Private bounded scene capture; readback runs are not performance tests."""
import argparse
import hashlib
import json
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
    pid = int(command('systemctl', 'show', 'kodi', '-p', 'MainPID', '--value').strip())
    if pid <= 0:
        raise RuntimeError('No Kodi service process')
    proc = Path('/proc') / str(pid)
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    digest = hashlib.sha256()
    with (proc / 'exe').open('rb') as binary:
        for block in iter(lambda: binary.read(1024 * 1024), b''):
            digest.update(block)
    return dict(pid=pid, start_ticks=int(fields[19]), binary_sha256=digest.hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--binary-sha256', help='Expected installed Kodi executable digest; always recorded.')
    parser.add_argument('--expected-native', type=int, choices=(0, 1))
    parser.add_argument('--expected-direct-packed', type=int, choices=(0, 1))
    args = parser.parse_args()
    if command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '--value').strip() != 'inactive':
        raise RuntimeError('Kodi must be inactive before capture')
    root = Path('/storage/dvbridge-output-captures')
    root.mkdir(exist_ok=True)
    request = root / 'request'
    if request.exists() or args.report.exists():
        raise RuntimeError('Fresh request/report required')
    if args.baseline:
        frames = json.loads(args.baseline.read_text())['frames']
        targets = [(row['pts'], 1) for row in frames]
    else:
        targets = [(1210000000, 0), (1220000000, 0), (1230000000, 0)]
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
    title = rpc('VideoLibrary.GetMovieDetails', {'movieid': 3391, 'properties': ['title']})['moviedetails']['title']
    if title != 'Saving Private Ryan':
        raise RuntimeError('Unexpected movie identity')
    existing = set(root.glob('frame-*'))
    request.write_text(f'{targets[0][0]:.17g} {targets[0][1]}\n')
    rpc('Player.Open', {'item': {'movieid': 3391}, 'options': {'resume': False}})
    player = None
    for _ in range(30):
        players = rpc('Player.GetActivePlayers')
        if players:
            player = players[0]['playerid']
            break
        time.sleep(1)
    if player is None:
        raise RuntimeError('No player')
    rpc('Player.Seek', {'playerid': player, 'value': {'time': {'hours': 0, 'minutes': 20,
                                                             'seconds': 0, 'milliseconds': 0}}})
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
                for field, expected in (('native', args.expected_native),
                                        ('direct_packed', args.expected_direct_packed)):
                    if expected is not None and info[field] != expected:
                        raise RuntimeError('Wrong captured rendering route: ' + field)
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
    args.report.write_text(json.dumps({'frames': captured, 'shutdown': state,
                                     'identity_before': identity, 'identity_after': final_identity}, indent=2))
    print('PASS capture/player-stop/shutdown', flush=True)


if __name__ == '__main__':
    main()
