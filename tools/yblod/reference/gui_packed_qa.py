"""Private GUI/overlay route captures; readback runs are not performance tests."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import time

from capture_scene import command, process_identity, rpc

CAPTURES = Path('/storage/dvbridge-output-captures')
OVERRIDE = Path('/run/systemd/system/kodi.service.d/yblod-native-playback.conf')
FULLSCREEN, OSD = 12005, 12901
RGBA_BYTES = 3840*2160*4


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--debug-overlay', action='store_true', help='Also test render-debug overlay on/off.')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-f0-9]{64}', args.binary_sha256):
        parser.error('A full lowercase Kodi executable SHA256 is required')
    if not args.config.is_file() or args.report.exists() or not args.report.parent.is_dir():
        parser.error('Existing config and a fresh report in an existing directory required')
    lines = args.config.read_text().splitlines()
    for name in ('NATIVE_RECONSTRUCTION', 'NATIVE_DIAGNOSTICS', 'NATIVE_FP32',
                 'NATIVE_COLOUR_NO_REIMPORT', 'NATIVE_NLQ_LUT', 'NATIVE_PACKED_OUTPUT', 'CAPTURE_OUTPUTS'):
        prefix = 'Environment=DVBRIDGE_'+name+'='
        if lines.count(prefix+'1') != 1 or sum(line.startswith(prefix) for line in lines) != 1:
            parser.error('Config must enable only the qualified native capture/packed route: '+name)
    pairs = [line for line in lines if line.startswith('Environment=DVBRIDGE_CAPTURE_PAIRS=')]
    if pairs and pairs != ['Environment=DVBRIDGE_CAPTURE_PAIRS=0']:
        parser.error('Paired renderer captures must be disabled')
    return args


def service_state():
    return dict(line.split('=', 1) for line in command('systemctl', 'show', 'kodi',
        '-p', 'ActiveState', '-p', 'Result', '-p', 'MainPID', '-p', 'ExecMainCode',
        '-p', 'ExecMainStatus').splitlines())


def current_window():
    return rpc('GUI.GetProperties', {'properties': ['currentwindow']})['currentwindow']


def wait_window(expected):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        window = current_window()
        if window['id'] == expected:
            time.sleep(2)
            if current_window()['id'] == expected:
                return window
        time.sleep(.1)
    raise RuntimeError('GUI window transition timed out')


def check_identity(expected):
    observed = process_identity()
    if observed != expected:
        raise RuntimeError('Kodi child process or executable changed during QA')
    return observed


def validate_frame(folder, info, direct):
    expected = dict(width=3840, height=2160, format='RGBA8 DV tunnel bottom up',
                    native=1, direct_packed=direct, qsv_mode=1, requested_pts=0, exact=0)
    if any(info.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Captured frame does not match the required native/QSV/output route')
    if any(not isinstance(info.get(key), (int, float)) or not math.isfinite(info[key]) or
           info[key] <= 1200000000 for key in ('pts', 'el_pts')):
        raise RuntimeError('Captured layer timestamps are invalid or precede the test scene')
    if (folder/'output.rgba').stat().st_size != RGBA_BYTES or (folder/'metadata.bin').stat().st_size <= 0:
        raise RuntimeError('Incomplete framebuffer or source-metadata capture')


def capture_next(label, direct, expected_window, identity):
    check_identity(identity)
    before = current_window()
    if before['id'] != expected_window:
        raise RuntimeError('Unexpected GUI state before capture')
    request = CAPTURES/'request'
    if request.exists():
        raise RuntimeError('Another output capture request is pending')
    existing = set(CAPTURES.glob('frame-*'))
    with request.open('x') as output:
        output.write('0 0\n')
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        new = set(CAPTURES.glob('frame-*'))-existing
        if len(new) > 1:
            raise RuntimeError('Ambiguous concurrent framebuffer captures')
        ready = [folder for folder in new if (folder/'frame.json').is_file()]
        if ready:
            folder = ready[0]
            try:
                info = json.loads((folder/'frame.json').read_text())
            except json.JSONDecodeError:
                time.sleep(.1)
                continue
            validate_frame(folder, info, direct)
            after = current_window()
            if after['id'] != expected_window:
                raise RuntimeError('GUI state changed during capture')
            observed = check_identity(identity)
            return dict(label=label, directory=str(folder), frame=info,
                        window_before=before, window_after=after, identity=observed)
        time.sleep(.1)
    raise RuntimeError('Framebuffer capture timed out; inspect Kodi log and private capture directories')


def wait_idle():
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        try:
            if rpc('Player.GetActivePlayers') == []:
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError('Kodi did not become reachable and idle')


def wait_player():
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        players = rpc('Player.GetActivePlayers')
        if len(players) == 1 and players[0]['type'] == 'video':
            return players[0]['playerid']
        time.sleep(1)
    raise RuntimeError('Expected one active video player')


def run(args):
    state = service_state()
    if state.get('ActiveState') != 'inactive' or state.get('Result') != 'success' or state.get('MainPID') != '0':
        raise RuntimeError('Kodi must initially be cleanly inactive')
    CAPTURES.mkdir(exist_ok=True)
    if (CAPTURES/'request').exists():
        raise RuntimeError('A capture request is already pending')
    count = 5 if args.debug_overlay else 3
    if shutil.disk_usage(CAPTURES).free < count*RGBA_BYTES+64*1024*1024:
        raise RuntimeError('Insufficient free storage for private QA captures')
    original = OVERRIDE.read_bytes()
    report = dict(schema='yblod.native-packed-gui-qa.v1', status='incomplete',
                  binary_sha256=args.binary_sha256, movie=dict(id=3391, title='Saving Private Ryan', seek_seconds=1200),
                  debug_overlay_requested=args.debug_overlay, captures=[],
                  scope='Private output-route/GUI functional QA; readbacks are not performance measurements or Dolby conformance.')
    try:
        shutil.copyfile(args.config, OVERRIDE)
        command('systemctl', 'daemon-reload')
        command('systemctl', 'start', 'kodi')
        wait_idle()
        time.sleep(20)
        if rpc('Player.GetActivePlayers'):
            raise RuntimeError('Kodi ceased being idle during startup settling')
        identity = process_identity()
        report['identity_before'] = identity
        if identity['binary_sha256'] != args.binary_sha256:
            raise RuntimeError('Unexpected Kodi executable')
        title = rpc('VideoLibrary.GetMovieDetails', {'movieid': 3391, 'properties': ['title']})['moviedetails']['title']
        if title != 'Saving Private Ryan':
            raise RuntimeError('Unexpected movie identity')
        rpc('Player.Open', {'item': {'movieid': 3391}, 'options': {'resume': False}})
        player = wait_player()
        rpc('Player.Seek', {'playerid': player, 'value': {'time': {'hours': 0, 'minutes': 20,
                                                              'seconds': 0, 'milliseconds': 0}}})
        time.sleep(10)
        wait_window(FULLSCREEN)
        report['captures'].append(capture_next('packed-before-gui', 1, FULLSCREEN, identity))
        rpc('Input.ShowOSD')
        wait_window(OSD)
        report['captures'].append(capture_next('gui-composed', 0, OSD, identity))
        rpc('Input.ShowOSD')
        wait_window(FULLSCREEN)
        report['captures'].append(capture_next('packed-after-gui', 1, FULLSCREEN, identity))
        if args.debug_overlay:
            rpc('Input.ExecuteAction', {'action': 'playerdebug'})
            time.sleep(2)
            report['captures'].append(capture_next('debug-overlay-composed', 0, FULLSCREEN, identity))
            rpc('Input.ExecuteAction', {'action': 'playerdebug'})
            time.sleep(2)
            report['captures'].append(capture_next('packed-after-debug-overlay', 1, FULLSCREEN, identity))
        report['window_before_stop'] = current_window()
        if report['window_before_stop']['id'] != FULLSCREEN:
            raise RuntimeError('GUI was not closed before player stop')
        check_identity(identity)
        rpc('Player.Stop', {'playerid': player})
        time.sleep(2)
        if rpc('Player.GetActivePlayers'):
            raise RuntimeError('Player did not stop')
        report['identity_after'] = check_identity(identity)
        command('systemctl', 'stop', 'kodi')
        report['shutdown'] = service_state()
        if report['shutdown'] != dict(ActiveState='inactive', Result='success', MainPID='0',
                                      ExecMainCode='1', ExecMainStatus='0'):
            raise RuntimeError('Kodi did not shut down cleanly')
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = str(error)
        raise
    finally:
        OVERRIDE.write_bytes(original)
        command('systemctl', 'daemon-reload')
        with args.report.open('x') as output:
            json.dump(report, output, indent=2, allow_nan=False)
    return report


if __name__ == '__main__':
    result = run(parse_args())
    print(json.dumps({'status': result['status'], 'captured_routes': [row['frame']['direct_packed']
                     for row in result['captures']], 'shutdown': result['shutdown']}), flush=True)
