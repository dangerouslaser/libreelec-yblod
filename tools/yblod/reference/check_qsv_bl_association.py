#!/usr/bin/env python3
"""Run the isolated CPU association fixture; no decoder or GPU access."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', default='yblod-ffmpeg9-decode:9.0.2')
    p.add_argument('--sudo', action='store_true')
    p.add_argument('--report', type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parent
    names = ('qsv_dovi_association.h', 'test_qsv_dovi_association.c')
    hashes = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}
    command = (['sudo', '-n'] if a.sudo else []) + ['docker', 'run', '--rm',
        '--memory=512m', '--memory-swap=512m', '--cpus=1', '--network=none',
        '--read-only', '--user', '0:0', '--tmpfs', '/tmp:rw,nosuid,exec,size=16m',
        '-v', f'{root}:/fixture:ro', '--entrypoint', '/bin/sh', a.image, '-c',
        'set -e; cc -std=c11 -Wall -Wextra -Werror /fixture/test_qsv_dovi_association.c '
        '-o /tmp/test; /tmp/test; echo MEMORY_PEAK; cat /sys/fs/cgroup/memory.peak; '
        'echo EVENTS; cat /sys/fs/cgroup/memory.events; echo SWAP; '
        'cat /sys/fs/cgroup/memory.swap.current']
    r = subprocess.run(command, text=True, capture_output=True)
    if r.returncode:
        raise RuntimeError(f'Association fixture failed with exit code {r.returncode}')
    lines = r.stdout.splitlines()
    peak = int(lines[lines.index('MEMORY_PEAK') + 1])
    start, end = lines.index('EVENTS') + 1, lines.index('SWAP')
    events = dict((k, int(v)) for k, v in (x.split() for x in lines[start:end]))
    swap = int(lines[end + 1])
    if peak <= 0 or peak > 536870912 or swap or not events or any(events.values()):
        raise RuntimeError('Resource qualification failed')
    report = {'schema': 'yblod.qsv-bl-association-foundation.v1',
        'all_contract_checks_passed': True, 'source_sha256': hashes,
        'memory_peak_bytes': peak, 'memory_events': events, 'swap_bytes': swap,
        'limits': {'memory_bytes': 536870912, 'extra_swap_bytes': 0,
                   'cpus': 1, 'network': 'none', 'gpu_access': False},
        'scope': 'Association ownership and identities only; no parser integration or hardware qualification.',
        'ffmpeg_integration_implemented': False, 'image': a.image}
    if a.report:
        with a.report.open('x') as f:
            json.dump(report, f, indent=2, allow_nan=False)
            f.write('\n')
    print(json.dumps(report, allow_nan=False))

if __name__ == '__main__':
    main()
