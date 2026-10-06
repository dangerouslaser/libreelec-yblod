#!/usr/bin/env python3
"""Guard and prepare patch19/20 + final-link-only serial LTO. Dry-run default."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BUILD = 'build.LibreELEC-Generic.x86_64-13.0-devel'
FILES = ('tools/dvbridge/dvbridge_fel.c', 'tools/dvbridge/dvbridge_fel.h',
         'xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp',
         'xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.h',
         'xbmc/cores/VideoPlayer/DVDCodecs/Video/DVDVideoCodecFFmpeg.cpp')
NEW = 'tools/dvbridge/dvbridge_fel_qsv_tokens.h'
PATCHES = ('kodi-9999-yblod-19-qsv-el-decoder.patch',
           'kodi-9999-yblod-20-qsv-el-observability.patch')
ENGINE = tuple(n + ext for n in ('native_egl_output_bridge', 'native_playback_context',
                                 'native_gpu_composer_fp32') for ext in ('.c', '.h')) + (
    'native_gpu_composer_backend_libplacebo.c', 'native_gpu_composer_fp32_backend.c')
DRIVER_SHA = 'd30f166ce5f9949b8195a8f6a4124baa302978b427a3714dcba09b2226cfe798'

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def serial_link(text):
    lines = text.splitlines(keepends=True)
    starts = [i for i, s in enumerate(lines) if s.startswith('build kodi.bin: ')]
    if len(starts) != 1:
        raise ValueError('Exactly one kodi.bin target required')
    start = starts[0]
    if not lines[start].startswith('build kodi.bin: CXX_EXECUTABLE_LINKER__kodi_Release '):
        raise ValueError('Unexpected Kodi link rule')
    end = start + 1
    while end < len(lines) and (lines[end].startswith(' ') or not lines[end].strip()):
        end += 1
    matches = [i for i in range(start + 1, end) if lines[i].startswith('  LINK_FLAGS =')]
    if len(matches) > 1:
        raise ValueError('Ambiguous final link flags')
    if matches:
        i = matches[0]
        lines[i] = lines[i].rstrip('\n') + ' -flto=1\n'
    else:
        lines.insert(start + 1, '  LINK_FLAGS = -flto=1\n')
    return ''.join(lines)

def run(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)

def validate_prepared(kodi, report):
    if report.get('source_applied') is not True or set(report['isolated_source_sha256']) != set((*FILES, NEW)):
        raise ValueError('Applied six-file preparation proof required')
    for name, sha in report['isolated_source_sha256'].items():
        if digest(kodi / name) != sha: raise ValueError('Prepared source changed')
    if set(report['engine_sha256']) != set(ENGINE):
        raise ValueError('Eight engine files required')
    for name, sha in report['engine_sha256'].items():
        if digest(kodi / 'tools/native_engine/experimental' / name) != sha:
            raise ValueError('Embedded engine changed')

def validate_final_command(command):
    rows = [r for r in command.splitlines() if ' -o kodi.bin ' in r]
    if len(rows) != 1: raise ValueError('One final Kodi command required')
    flags = re.findall(r'(?<!\S)-flto(?:=[^\s]+)?', rows[0])
    if not flags or flags[-1] != '-flto=1': raise ValueError('Final LTO worker override missing')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk-project', required=True, type=Path)
    p.add_argument('--recipe-root', required=True, type=Path)
    p.add_argument('--expected-manifest', required=True, type=Path)
    p.add_argument('--backup-parent', required=True, type=Path)
    p.add_argument('--apply-source', action='store_true')
    p.add_argument('--report', required=True, type=Path)
    a = p.parse_args()
    kodi = a.sdk_project.resolve(strict=True) / BUILD / 'build/kodi-22.0rc1-Piers'
    build = kodi / '.x86_64-libreelec-linux-gnu'
    recipe = a.recipe_root.resolve(strict=True)
    expected = json.loads(a.expected_manifest.read_text())
    if set(expected['source_sha256']) != set(FILES):
        raise ValueError('Manifest must identify exactly five baseline source files')
    for name in FILES:
        if digest(kodi / name) != expected['source_sha256'][name]:
            raise ValueError('Baseline source changed')
    if (kodi / NEW).exists():
        raise ValueError('New QSV token header unexpectedly exists')
    if digest(build / 'kodi.bin') != expected['binary_sha256']:
        raise ValueError('Baseline binary changed')
    if a.report.exists(): raise ValueError('Fresh preparation report required')
    engine = {}
    for name in ENGINE:
        sha = digest(recipe / 'engine/experimental' / name)
        if digest(kodi / 'tools/native_engine/experimental' / name) != sha:
            raise ValueError('Embedded/canonical engine disagreement')
        engine[name] = sha
    backup = Path(tempfile.mkdtemp(prefix='qsv-el-pre19-', dir=a.backup_parent.resolve(strict=True)))
    source = backup / 'source'
    for name in FILES:
        dest = source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kodi / name, dest)
    shutil.copy2(build / 'kodi.bin', backup / 'kodi-retained-baseline.bin')
    shutil.copy2(build / 'build.ninja', backup / 'build.ninja')
    shutil.copy2(build / 'CMakeFiles/rules.ninja', backup / 'rules.ninja')
    shutil.copy2(build / 'CMakeCache.txt', backup / 'CMakeCache.txt')
    shutil.copy2(build / 'compile_commands.json', backup / 'compile_commands.json')
    shutil.copy2(a.expected_manifest, backup / 'baseline-manifest.json')
    patches = recipe / 'packages/mediacenter/kodi/patches'
    for name in PATCHES:
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patches / name)], source)
    if a.apply_source:
        for name in PATCHES:
            run(['patch', '--batch', '--fuzz=0', '-p1', '--dry-run', '-i', str(patches / name)], kodi)
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patches / name)], kodi)
        for name in (*FILES, NEW):
            if digest(kodi / name) != digest(source / name):
                raise ValueError('Applied source differs from isolated proof')
    result = {'source_applied': a.apply_source, 'backup_directory': str(backup),
                      'baseline_binary_sha256': expected['binary_sha256'],
                      'isolated_source_sha256': {n: digest(source / n) for n in (*FILES, NEW)},
                      'engine_sha256': engine, 'build_started': False}
    with a.report.open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
