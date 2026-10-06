"""Bounded disposable image build; preserve intermediate containers and logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE_SHA = '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'
BASE_SHA = 'sha256:c33565031c2bfbbe2eb8ede588b63f7972d3fb34978572ebb1d2f46bf7d2296d'
BASE = 'intel-dv-buildcheck:20260925'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-archive', required=True, type=Path)
    parser.add_argument('--work-parent', required=True, type=Path)
    parser.add_argument('--tag', default='yblod-ffmpeg9-decode:9.0.2')
    args = parser.parse_args()
    if not args.work_parent.is_dir() or not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]+', args.tag):
        raise ValueError('Existing private build parent and valid disposable image tag required')
    if hashlib.sha256(args.source_archive.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Wrong pristine FFmpeg9.0.2 archive')
    base = json.loads(subprocess.check_output(['docker', 'image', 'inspect', BASE], text=True))[0]
    if base['Id'] != BASE_SHA:
        raise ValueError('SDK image differs from inspected compiler/assembler base')
    work = Path(tempfile.mkdtemp(prefix='ffmpeg9-decode-build-', dir=args.work_parent))
    shutil.copyfile(args.source_archive, work/'ffmpeg-9.0.2.tar.xz')
    shutil.copyfile(Path(__file__).with_name('Dockerfile.ffmpeg9-decode-apis'), work/'Dockerfile')
    environment = dict(os.environ, DOCKER_BUILDKIT='0')
    command = ['docker', 'build', '--rm=false', '--force-rm=false', '--memory=4g',
        '--memory-swap=4g', '--cpu-period=100000', '--cpu-quota=100000', '-t', args.tag, str(work)]
    log_path = work/'build.log'
    with log_path.open('x') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment)
    log = log_path.read_text()
    ids = list(dict.fromkeys(re.findall(r'Running in ([a-f0-9]{12,64})', log)))
    states = []
    for container in ids:
        row = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
        states.append(dict(container_id=row['Id'], oom_killed=row['State']['OOMKilled'],
            exit_code=row['State']['ExitCode'], memory_limit=row['HostConfig']['Memory'],
            memory_swap_limit=row['HostConfig']['MemorySwap'], cpu_quota=row['HostConfig']['CpuQuota'],
            cpu_period=row['HostConfig']['CpuPeriod']))
    result = dict(schema='yblod.ffmpeg9-container-build-results.v1', source_version='9.0.2',
        source_archive_sha256=SOURCE_SHA, base_image_id=BASE_SHA, requested_tag=args.tag,
        process_exit_code=process.returncode, intermediate_containers=states,
        peak_memory_measured=False, host_packages_or_services_changed=False)
    if process.returncode == 0:
        image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.tag], text=True))[0]
        result['image_id'] = image['Id']
    (work/'build-results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    if process.returncode or any(row['oom_killed'] for row in states):
        raise RuntimeError('Container build failed; logs and containers retained for inspection')


if __name__ == '__main__':
    main()
