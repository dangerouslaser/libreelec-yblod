#!/usr/bin/env python3
"""Capture bounded native-engine timings without recording media URLs or raw logs."""
import argparse
import fcntl
import json
import pathlib
import subprocess
import time
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('host')
p.add_argument('file')
p.add_argument('output', type=pathlib.Path)
p.add_argument('--seconds', type=int, default=20)
p.add_argument('--overlay', choices=['none', 'home'], default='none')
p.add_argument('--memory', action='store_true', help='Measure whole-system N150 IMC traffic')
a = p.parse_args()
lock = open('/tmp/yblod-native-profile-' + a.host + '.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

def rpc(method, params=None):
    data = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params or {})).encode()
    request = urllib.request.Request('http://' + a.host + ':8080/jsonrpc', data,
                                     {'Content-Type': 'application/json'})
    result = json.load(urllib.request.urlopen(request, timeout=8))
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result['result']

def ssh(command):
    return subprocess.check_output(['sshpass', '-e', 'ssh', 'root@' + a.host, command], text=True)

for player in rpc('Player.GetActivePlayers'):
    rpc('Player.Stop', {'playerid': player['playerid']})
for _ in range(30):
    if not rpc('Player.GetActivePlayers'):
        break
    time.sleep(.2)
else:
    raise RuntimeError('Previous playback did not stop')
time.sleep(1)
start = ssh('date -u +%Y-%m-%dT%H:%M:%S').strip()
log_start = int(ssh('wc -l < /storage/.kodi/temp/kodi.log').strip())
rpc('Player.Open', {'item': {'file': a.file}})
for _ in range(60):
    players = rpc('Player.GetActivePlayers')
    if players:
        state = rpc('Player.GetProperties', {'playerid': players[0]['playerid'], 'properties': ['time']})
        t = state['time']
        if t['hours'] * 3600 + t['minutes'] * 60 + t['seconds'] >= 2:
            break
    time.sleep(.25)
else:
    raise RuntimeError('Playback did not reach the startup gate')
rpc('GUI.SetFullscreen', {'fullscreen': True})
if a.overlay == 'home':
    rpc('GUI.ActivateWindow', {'window': 'home'})
memory = None
if a.memory:
    memory = ssh('perf stat -a -x, -e uncore_imc_free_running_0/data_read/,'
                 'uncore_imc_free_running_0/data_write/ sleep ' + str(a.seconds) + ' 2>&1')
else:
    time.sleep(a.seconds)
window = rpc('GUI.GetProperties', {'properties': ['currentwindow', 'fullscreen']})
qualified_window = window['currentwindow']['id'] == (10000 if a.overlay == 'home' else 12005)
for player in rpc('Player.GetActivePlayers'):
    rpc('Player.Stop', {'playerid': player['playerid']})
time.sleep(1)
journal = ssh("journalctl -u kodi --since '" + start + " UTC' --no-pager")
events = []
for line in journal.splitlines():
    if '{' not in line:
        continue
    try:
        item = json.loads(line[line.index('{'):])
    except ValueError:
        continue
    if any(k.startswith(('source_', 'overlay_', 'p010_')) for k in item):
        events.append(item)
log = ssh('tail -n +' + str(log_start + 1) + ' /storage/.kodi/temp/kodi.log')
timings = [line for line in log.splitlines() if any(s in line for s in (
    'Private source transition:', 'Private source frame:', 'DVBridge playback health:',
    'Private native GUI cache:'))]
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(dict(host=a.host, start_utc=start, overlay=a.overlay,
    duration_seconds=a.seconds, window=window, qualified_window=qualified_window, memory_perf=memory,
    gpu_events=events, timing_lines=timings), indent=2) + '\n')
print(json.dumps(dict(output=str(a.output), gpu_events=len(events), timing_lines=len(timings))))
