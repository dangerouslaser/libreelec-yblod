"""Set and restore playback-latched colour offsets only while Kodi is idle."""
import argparse
import json
from pathlib import Path
import time
from capture_scene import command, rpc
from run_long_matrix import wait_rpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '--value').strip() != 'inactive':
        raise RuntimeError('Kodi must be cleanly stopped')
    if not args.restore and args.snapshot.exists():
        raise RuntimeError('Fresh settings snapshot required')
    command('systemctl', 'start', 'kodi')
    wait_rpc()
    time.sleep(20)
    if rpc('Player.GetActivePlayers'):
        raise RuntimeError('Settings test requires idle Kodi')
    setting = 'dvbridge.matchhardware'
    before = rpc('Settings.GetSettingValue', {'setting': setting})['value']
    if type(before) is not bool:
        raise RuntimeError('Unexpected offset setting type')
    if args.restore:
        saved = json.loads(args.snapshot.read_text())
        if saved.get('setting') != setting or type(saved.get('original')) is not bool:
            raise RuntimeError('Invalid settings snapshot')
        target = saved['original']
    else:
        with args.snapshot.open('x') as handle:
            json.dump(dict(setting=setting, original=before), handle)
        target = False
    if rpc('Settings.SetSettingValue', {'setting': setting, 'value': target}) is not True:
        raise RuntimeError('Offset setting update failed')
    after = rpc('Settings.GetSettingValue', {'setting': setting})['value']
    if after is not target:
        raise RuntimeError('Offset setting verification failed')
    command('systemctl', 'stop', 'kodi')
    state = command('systemctl', 'show', 'kodi', '-p', 'ActiveState', '-p', 'Result', '-p', 'MainPID')
    if set(state.splitlines()) != {'ActiveState=inactive', 'Result=success', 'MainPID=0'}:
        raise RuntimeError(state)
    print(json.dumps(dict(before=before, after=after, restored=args.restore, clean_shutdown=True)))


if __name__ == '__main__':
    main()
