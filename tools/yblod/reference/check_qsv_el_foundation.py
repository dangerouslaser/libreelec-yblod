#!/usr/bin/env python3
"""Reproduce patch19 source/CPU-only tests; never initialize GPU hardware."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

BUILD = 'build.LibreELEC-Generic.x86_64-13.0-devel'
PATCH = 'kodi-9999-yblod-19-qsv-el-decoder.patch'


def run(command, label, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        # Do not emit private source/compiler output as public evidence or
        # confuse a setup failure with a hardware result.
        raise RuntimeError(f'{label} failed with exit code {result.returncode}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-project', required=True, type=Path)
    parser.add_argument('--recipe-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--scratch-parent', required=True, type=Path)
    parser.add_argument('--sdk-image', default='intel-dv-buildcheck:20260925')
    parser.add_argument('--mock-image', default='yblod-ffmpeg9-decode:9.0.2')
    parser.add_argument('--sudo', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    sdk = args.sdk_project.resolve(strict=True)
    recipe = args.recipe_root.resolve(strict=True)
    scratch_parent = args.scratch_parent.resolve(strict=True)
    kodi = sdk / BUILD / 'build/kodi-22.0rc1-Piers'
    patch = recipe / 'packages/mediacenter/kodi/patches' / PATCH
    fixtures = recipe / 'tools/yblod/reference'
    if not kodi.is_dir() or not patch.is_file():
        parser.error('Required Kodi source and public patch19 must exist')
    # Kept for review/reproduction; no recursive deletion of user directories.
    scratch = Path(tempfile.mkdtemp(prefix='qsv-el-foundation-', dir=scratch_parent))
    work = scratch / 'tools/dvbridge'
    work.mkdir(parents=True)
    for name in ('dvbridge_fel.c', 'dvbridge_fel.h'):
        shutil.copy2(kodi / 'tools/dvbridge' / name, work / name)
    for name in ('test_dvbridge_fel_qsv_tokens.c', 'test_dvbridge_fel_qsv_mock.c'):
        shutil.copy2(fixtures / name, scratch / name)
    # Both checks require exact hunks. The actual build receives only a dry-run.
    common_patch = ['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)]
    run(common_patch + ['--dry-run'], 'actual-source patch dry-run', kodi)
    run(common_patch, 'isolated-source patch application', scratch)
    docker = ['sudo', '-n', 'docker'] if args.sudo else ['docker']
    limits = ['run', '--rm', '--user', '0:0', '--memory=512m', '--memory-swap=512m', '--cpus=1',
              '--network=none', '--read-only', '--tmpfs', '/tmp:rw,nosuid,exec,size=32m',
              '-v', f'{scratch}:/validation:ro', '--entrypoint', '/bin/sh']
    compiler = f'/build/{BUILD}/toolchain/bin/x86_64-libreelec-linux-gnu-gcc'
    include = f'/build/{BUILD}/build/ffmpeg-9.0.2'
    run(docker + limits + ['-e', 'CCACHE_DISABLE=1', '-v', f'{sdk}:/build:ro',
        args.sdk_image, '-c',
        f'{compiler} -std=c11 -Wall -Wextra -Werror -fsyntax-only '
        f'-I{include} -I/validation/tools/dvbridge /validation/tools/dvbridge/dvbridge_fel.c'],
        'exact SDK syntax')
    run(docker + limits + [args.mock_image, '-c',
        'cc -std=c11 -Wall -Wextra -Werror -I/validation/tools/dvbridge '
        '/validation/test_dvbridge_fel_qsv_tokens.c -o /tmp/tokens && /tmp/tokens'],
        'strict option and timestamp tokens')
    run(docker + limits + [args.mock_image, '-c',
        'cc -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections '
        '-I/opt/ffmpeg-source -I/validation/tools/dvbridge '
        '/validation/test_dvbridge_fel_qsv_mock.c /opt/ffmpeg-source/libavutil/libavutil.a '
        '-Wl,--gc-sections -lvpl -lva -lva-drm -lm -lpthread -ldl '
        '-o /tmp/receive-mock && /tmp/receive-mock'], 'real AVFrame/mock receive contract')
    result = {
        'schema': 'yblod-qsv-el-reproduction-v1', 'all_checks_passed': True,
        'checks': ['actual_source_strict_patch_dry_run', 'isolated_patch_application',
                   'exact_sdk_syntax', 'strict_option_and_timestamp_tokens',
                   'real_AVFrame_mock_receive_contract'],
        'limits_per_test_container': {'memory_bytes': 536870912, 'extra_swap_bytes': 0,
                                      'cpus': 1, 'network': 'none', 'gpu_passthrough': False},
        'peak_memory_measured': False, 'actual_kodi_source_modified': False,
        'hardware_decode_or_zero_copy_qualified': False,
        'sdk_image': args.sdk_image, 'mock_image': args.mock_image,
        'scope': 'CPU source/contracts only; actual direct-map, hardware timestamp propagation, pixels and playback remain unqualified.'}
    if args.report:
        with args.report.open('x') as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
            handle.write('\n')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
