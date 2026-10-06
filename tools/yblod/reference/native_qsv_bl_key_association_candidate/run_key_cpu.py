#!/usr/bin/env python3
"""One owned bounded CPU-only fixture; preserve its failure records."""
import json
from pathlib import Path
import signal
import subprocess
import time

IMAGE = 'sha256:33c6601e0e65d900edc712bdb6f40bb1e680669d5ffb76ecd014c8e6f2ec0e1e'
SOURCE = Path(__file__).resolve().parent
OUT = SOURCE / 'cpu-key-linkfixed-attempt'

def docker(*args):
    return subprocess.run(['docker', *args], text=True, capture_output=True,
                          check=True, timeout=15).stdout

def interrupted(*unused):
    raise RuntimeError('Owned CPU fixture interrupted')

def main():
    OUT.mkdir(mode=0o700)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    ident = None
    try:
        ident = docker('create', '--name', 'yblod-qsv-bl-irap-key-linkfixed-cpu-20261006',
                       '--memory=512m', '--memory-swap=512m', '--cpus=1', '--network=none',
                       '--read-only', '--user', '0:0', '--tmpfs', '/tmp:rw,nosuid,exec,size=16m',
                       '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{SOURCE}:/candidate:ro',
                       '--entrypoint', '/bin/sh', IMAGE,
                       '/candidate/check_key_cpu.sh').strip()
        assert len(ident) == 64 and all(c in '0123456789abcdef' for c in ident)
        before = json.loads(docker('inspect', ident))[0]
        h = before['HostConfig']
        assert before['Id'] == ident and before['Image'] == IMAGE and before['Config']['Image'] == IMAGE
        assert h['Memory'] == 536870912 and h['MemorySwap'] == 536870912
        assert h['NanoCpus'] == 1000000000 and h['NetworkMode'] == 'none' and h['ReadonlyRootfs']
        assert not h['Privileged'] and not h.get('Devices') and not h.get('DeviceRequests')
        assert [(m['Destination'], m['Source'], m['RW']) for m in before['Mounts'] if m['Type'] == 'bind'] == [('/candidate', str(SOURCE), False)]
        (OUT / 'container-before.json').write_text(json.dumps(before))
        docker('start', ident)
        print(json.dumps({'owned_container': ident}), flush=True)
        deadline = time.monotonic() + 120
        while True:
            state = json.loads(docker('inspect', ident))[0]['State']
            if not state['Running']:
                if state['ExitCode'] or state['OOMKilled']:
                    raise RuntimeError('CPU fixture failed')
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('Owned CPU fixture deadline')
            # Preserve numeric cgroup observations even if compiler/test fails later.
            try:
                sample = docker('exec', ident, '/bin/sh', '-c',
                                'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.swap.current /sys/fs/cgroup/memory.swap.peak')
                (OUT / 'last-resource-sample.txt').write_text(sample)
            except subprocess.CalledProcessError:
                if json.loads(docker('inspect', ident))[0]['State']['Running']:
                    raise
            time.sleep(1)
    finally:
        if ident:
            state = json.loads(docker('inspect', ident))[0]['State']
            if state['Running']:
                docker('stop', '--time', '2', ident)
            after = json.loads(docker('inspect', ident))[0]
            assert after['Id'] == ident and not after['State']['Running']
            (OUT / 'container-terminal.json').write_text(json.dumps(after))
            logs = subprocess.run(['docker', 'logs', ident], text=True,
                                  capture_output=True, timeout=15, check=True)
            (OUT / 'stdout-stderr.txt').write_text(logs.stdout + logs.stderr)

if __name__ == '__main__':
    main()
