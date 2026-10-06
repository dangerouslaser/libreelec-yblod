#!/usr/bin/env python3
"""CPU-only reproduction of patch20, applied to an isolated patch19 tree."""
import argparse
import ast
import json
from pathlib import Path
import shlex
import shutil
import re
import subprocess
import tempfile
from check_qsv_el_foundation import BUILD, run

KODI = Path(BUILD) / 'build/kodi-22.0rc1-Piers'
RENDERER = Path('xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp')
CODEC = Path('xbmc/cores/VideoPlayer/DVDCodecs/Video/DVDVideoCodecFFmpeg.cpp')


def capture_extent(source):
    capture = source.split('void CDVBridgeGLES::CaptureOutput(', 1)[1]
    size = int(re.search(r'char info\[(\d+)\];', capture)[1])
    block = capture.split('const int length = std::snprintf(info, sizeof(info),', 1)[1]
    block = block.split('m_outputCapturePts,', 1)[0]
    fmt = ''.join(ast.literal_eval(value) for value in re.findall(r'"(?:[^"\\]|\\.)*"', block))
    # %.17g finite binary64 needs at most24 chars; even NaN/Inf are shorter.
    # Deliberately allow signed INT_MIN for every flag and full uint64 serial,
    # exceeding the actual0/1 flags and positive int64 marker contract.
    worst = fmt.replace('%.17g', '-1.7976931348623157e+308')
    worst = worst.replace('%llu', '18446744073709551615').replace('%d', '-2147483648')
    if '%' in worst or len(worst.encode()) + 1 > size:
        raise RuntimeError('Capture JSON format no longer fits its buffer')
    return {'buffer_bytes': size, 'conservative_extent_including_nul': len(worst.encode()) + 1}


def sdk_syntax():
    original = Path('/build') / KODI
    commands = json.loads((original / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
    compiler = Path('/build') / BUILD / 'toolchain/bin/x86_64-libreelec-linux-gnu-gcc'
    run([str(compiler), '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only',
         f'-I/build/{BUILD}/build/ffmpeg-9.0.2', '-I/validation/tools/dvbridge',
         '/validation/tools/dvbridge/dvbridge_fel.c'], 'EL C SDK syntax')
    for relative, native in ((RENDERER, True), (RENDERER, False), (CODEC, True)):
        matches = [record for record in commands if record['file'] == str(original / relative)]
        if len(matches) != 1:
            raise RuntimeError('Missing or ambiguous SDK compile command')
        record = matches[0]
        command = shlex.split(record['command'])
        filtered, index = [], 0
        while index < len(command):
            value = command[index]
            if value == '-o':
                index += 2
                continue
            if value == '-c' or value == record['file']:
                index += 1
                continue
            if not native and value.startswith('-DHAVE_YBLOD_NATIVE_PLAYBACK'):
                index += 1
                continue
            filtered.append(value)
            index += 1
        # Staged header/source take precedence; remaining headers are read-only
        # originals. No object generation, linking, compiler cache or GPU access.
        filtered[1:1] = ['-I/validation/tools/dvbridge',
                          f'-I/validation/{RENDERER.parent}', f'-I{original / relative.parent}']
        filtered.extend(['-fsyntax-only', str(Path('/validation') / relative)])
        run(filtered, f'{relative.name} native={native} SDK syntax', record['directory'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside-sdk', action='store_true')
    parser.add_argument('--sdk-project', type=Path)
    parents = Path(__file__).resolve().parents
    parser.add_argument('--recipe-root', type=Path, default=parents[3] if len(parents) > 3 else Path('/validation'))
    parser.add_argument('--scratch-parent', type=Path)
    parser.add_argument('--sudo', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.inside_sdk:
        sdk_syntax()
        return
    if args.sdk_project is None or args.scratch_parent is None:
        parser.error('--sdk-project and --scratch-parent required')
    sdk = args.sdk_project.resolve(strict=True)
    recipe = args.recipe_root.resolve(strict=True)
    scratch = Path(tempfile.mkdtemp(prefix='qsv-el-observability-',
                                  dir=args.scratch_parent.resolve(strict=True)))
    for relative in (Path('tools/dvbridge/dvbridge_fel.c'), Path('tools/dvbridge/dvbridge_fel.h'),
                     RENDERER, RENDERER.with_suffix('.h'), CODEC):
        target = scratch / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sdk / KODI / relative, target)
    fixtures = recipe / 'tools/yblod/reference'
    for name in ('check_qsv_el_foundation.py', 'check_qsv_el_observability.py',
                 'test_dvbridge_fel_qsv_observability.c'):
        shutil.copy2(fixtures / name, scratch / name)
    patches = recipe / 'packages/mediacenter/kodi/patches'
    for name in ('kodi-9999-yblod-19-qsv-el-decoder.patch',
                 'kodi-9999-yblod-20-qsv-el-observability.patch'):
        command = ['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patches / name)]
        run(command + ['--dry-run'], name + ' isolated dry-run', scratch)
        run(command, name + ' isolated apply', scratch)
    extent = capture_extent((scratch / RENDERER).read_text())
    docker = ['sudo', '-n', 'docker'] if args.sudo else ['docker']
    limits = ['run', '--rm', '--user', '0:0', '--memory=512m', '--memory-swap=512m',
              '--cpus=1', '--network=none', '--read-only', '--tmpfs', '/tmp:rw,nosuid,exec,size=32m',
              '-v', f'{scratch}:/validation:ro', '--entrypoint', '/bin/sh']
    run(docker + limits + ['-e', 'CCACHE_DISABLE=1', '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '-v', f'{sdk}:/build:ro', 'intel-dv-buildcheck:20260925', '-c',
        'python3 /validation/check_qsv_el_observability.py --inside-sdk'], 'SDK syntax contracts')
    run(docker + limits + ['yblod-ffmpeg9-decode:9.0.2', '-c',
        'cc -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections '
        '-I/opt/ffmpeg-source -I/validation/tools/dvbridge '
        '/validation/test_dvbridge_fel_qsv_observability.c /opt/ffmpeg-source/libavutil/libavutil.a '
        '-Wl,--gc-sections -lvpl -lva -lva-drm -lm -lpthread -ldl '
        '-o /tmp/observe && /tmp/observe'], 'AVFrame route/association mock')
    result = {'schema': 'yblod-qsv-el-observability-tests-v1', 'all_checks_passed': True,
              'strict_isolated_patch_chain': [19, 20], 'sdk_c_syntax': True,
              'sdk_renderer_native_on_and_off_syntax': True, 'sdk_codec_syntax': True,
              'real_AVFrame_mock_route_tests': True, 'actual_kodi_source_modified': False,
              'limits_per_container': {'memory_bytes': 536870912, 'extra_swap_bytes': 0,
                  'cpus': 1, 'network': 'none', 'gpu_passthrough': False},
              'container_peak_memory_measured': False,
              'capture_json_buffer_extent': extent,
              'hardware_decode_mapping_or_native_use_qualified': False}
    if args.report:
        with args.report.open('x') as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
            handle.write('\n')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
