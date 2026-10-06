#!/usr/bin/env python3
"""One explicitly approved Ollie BL diagnostic; input path remains private."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

ROOT = Path('/home/bryan/Projects/libreelec-yblod')
PUBLIC = Path('/home/bryan/Projects/libreelec-yblod-reconstruction')
CONTROL = Path(__file__).resolve().parent
CANDIDATE = PUBLIC / 'target/qsv-bl-keyflag-library-20261006'
PROBE = PUBLIC / 'target/qsv-bl-duration-probe-20261006/lifecycle-v2/compile-lifecycle-v2-attempt'
OUT = PUBLIC / 'target/qsv-bl-picture-lifecycle-runtime-20261006'
IMAGE = 'sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e'
HELPERS = {
    'observe_live_el_qsv_probe.py':'deeefe2cbe27b452c851bbbdaab670ba20e50c3f4a3cb9b4499ddc46ef20ee95',
    'target_el_qsv_live_handshake.py':'6c09e91a680a93b1a7dc93d16870f27f2099d8c854409aecc28f54070f62faee',
    'collect_el_qsv_target_identity.py':'c670f8b7e7145e032be77a2a615a3f25d8b164fd9ff60aab63d29b4c2e54c0b9',
    'run_target_el_qsv_probe.py':'c0f139c08246d86acf0e4b4de907256b7016e8a9dc47bcc9be404743d4dbc6be',
    'capture_scene.py':'2816454523b63aaaf00ad5de4417b0fe76da9fe3ae6fc9d7ddeb44c52e7952e6',
}

def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()

def source_stat(path):
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

def available_memory():
    return next(int(row.split()[1])*1024 for row in Path('/proc/meminfo').read_text().splitlines()
                if row.startswith('MemAvailable:'))

def idle():
    request = urllib.request.Request('http://127.0.0.1:8086/jsonrpc',
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':'Player.GetActivePlayers'}).encode(),
        headers={'Content-Type':'application/json'})
    value = json.load(urllib.request.urlopen(request, timeout=2))['result']
    if not isinstance(value,list):
        raise ValueError('Valid idle RPC required')
    return not value

def docker(*args):
    return subprocess.run(['docker',*args],text=True,capture_output=True,timeout=15,check=True).stdout

def main():
    os.umask(0o077)
    media = Path(os.environ['PRIVATE_INPUT_PATH']).resolve(strict=True)
    if not media.is_file() or not idle() or available_memory() < 6442450944:
        raise ValueError('Private regular input and idle Kodi required')
    before = source_stat(media)
    source_files = {CONTROL/name:sha(CONTROL/name) for name in
                    ('check_picture_lifecycle_qsv_bl_runtime.py','run_picture_lifecycle_qsv_bl_probe.py','observe_picture_lifecycle_qsv_bl_probe.py','observe_picture_transport_qsv_bl_probe.py','observe_live_el_qsv_probe_1536.py')}
    if source_files[CONTROL/'observe_picture_lifecycle_qsv_bl_probe.py'] != '73d4539b061ca6ee0fc1caddf8e862d6bdb481368ea15f3f363b68571e636d4e' or source_files[CONTROL/'observe_picture_transport_qsv_bl_probe.py'] != '2b2f58cde3a4cba251c693debe54d30c20a05e4c4d62135887f53ae89b787186' or source_files[CONTROL/'observe_live_el_qsv_probe_1536.py'] != 'dccc1a89ddeb386aa1dbd0a807cbb45312cbda80ea5ac7720e73cd47766fee59':
        raise ValueError('Reviewed BL observer source differs')
    for name,wanted in HELPERS.items():
        path = PUBLIC / 'tools/yblod/reference' / name
        if sha(path) != wanted:
            raise ValueError('Reviewed shared observer source differs')
        source_files[path] = wanted
    OUT.mkdir(mode=0o700)
    mounts = {'/build':(ROOT,False),'/public':(PUBLIC,False),'/candidate':(CANDIDATE,False),
              '/probe':(PROBE,False),'/duration-source':(PUBLIC/'target/qsv-bl-duration-probe-20261006/lifecycle-v2',False),'/control':(CONTROL,False),'/input/source.mkv':(media,False),'/diagnostics':(OUT,True)}
    args = ['create','--name','yblod-qsv-bl-picture-lifecycle-runtime-20261006',
            '--memory=1536m','--memory-swap=1536m','--cpus=1','--network=none','--read-only',
            '--tmpfs','/tmp:rw,nosuid,exec,size=32m','--device=/dev/dri/renderD128',
            '--group-add','109','--user','0:0','-e','PYTHONDONTWRITEBYTECODE=1',
            '-e','PYTHONPATH=/control:/public/tools/yblod/reference']
    for destination,(source,writable) in mounts.items():
        args += ['-v',f'{source}:{destination}:{"rw" if writable else "ro"}']
    args += ['--entrypoint','/bin/sh',IMAGE,'-c','python3 /control/run_picture_lifecycle_qsv_bl_probe.py']
    ident = None
    def interrupted(*unused):
        raise RuntimeError('Owned diagnostic interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    signal.signal(signal.SIGHUP,interrupted)
    try:
        ident = docker(*args).strip()
        if len(ident)!=64 or any(c not in '0123456789abcdef' for c in ident):
            raise ValueError('Exact owned container ID required')
        configured = json.loads(docker('inspect',ident))[0]
        h = configured['HostConfig']
        assert configured['Id']==ident and configured['Image']==IMAGE and configured['Config']['Image']==IMAGE
        assert h['Memory']==1610612736 and h['MemorySwap']==1610612736 and h['NanoCpus']==1000000000
        assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and not h['Privileged'] and not h.get('DeviceRequests')
        assert h['Devices']==[{'PathOnHost':'/dev/dri/renderD128','PathInContainer':'/dev/dri/renderD128','CgroupPermissions':'rwm'}]
        assert {m['Destination']:(Path(m['Source']),m['RW']) for m in configured['Mounts'] if m['Type']=='bind'}==mounts
        (OUT/'container-before-private.json').write_text(json.dumps(configured))
        docker('start',ident)
        deadline = time.monotonic()+240
        while True:
            state = json.loads(docker('inspect',ident))[0]['State']
            if not state['Running']:
                break
            if time.monotonic()>=deadline or not idle() or available_memory() < 3221225472:
                raise RuntimeError('Owned deadline or Kodi activity')
            time.sleep(1)
        logs = subprocess.run(['docker','logs',ident],text=True,capture_output=True,timeout=15)
        (OUT/'controller-stdout-private.log').write_text(logs.stdout)
        (OUT/'controller-stderr-private.log').write_text(logs.stderr)
        final = json.loads(docker('inspect',ident))[0]
        (OUT/'container-after-private.json').write_text(json.dumps(final))
        if final['Id']!=ident or final['State']['ExitCode']!=0 or final['State']['OOMKilled'] or final['State']['Running']:
            raise ValueError('Successful terminal diagnostic required')
        if before!=source_stat(media) or not idle() or any(sha(path)!=wanted for path,wanted in source_files.items()):
            raise ValueError('Source, observer code or idle identity changed')
        # Container writes private files as root; Docker stdout is the same safe
        # scalar record and does not require relaxing private file permissions.
        result = json.loads(logs.stdout)
        if result.get('pass') is not True:
            raise ValueError('Strict raw and actual live identity proof required')
        life = result['controlled_packet_window_lifecycle']
        if any(type(epoch['event_count']) is not int or epoch['event_count'] != 725
               for epoch in life['epochs']):
            raise ValueError('Exactly 725 associated pictures required in each fixture epoch')
        result.update(container_exit_code=0,container_oom_killed=False,exact_limits_and_mounts_verified=True,
                      image=IMAGE,kodi_idle_before_during_after=True,private_input_stat_identity_unchanged=True,
                      shared_observer_code_unchanged=True)
        (OUT/'runtime-results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        if ident is not None:
            final = json.loads(docker('inspect',ident))[0]
            if final['Id']!=ident:
                raise RuntimeError('Owned ID changed')
            if final['State']['Running']:
                docker('stop','--time','5',ident)
                docker('wait',ident)
            final = json.loads(docker('inspect',ident))[0]
            (OUT/'container-terminal-private.json').write_text(json.dumps(final))
            logs = subprocess.run(['docker','logs',ident],text=True,capture_output=True,timeout=15)
            (OUT/'controller-stdout-private.log').write_text(logs.stdout)
            (OUT/'controller-stderr-private.log').write_text(logs.stderr)
            if final['State']['Running']:
                raise RuntimeError('Owned termination unconfirmed')

if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'scope':'BL runtime diagnostic','pass':False,'error_type':type(error).__name__}))
        raise SystemExit(1)
