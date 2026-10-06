import json
import shlex
import subprocess
from pathlib import Path
base = Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel')
root = base / 'build/kodi-22.0rc1-Piers'
rows = json.loads((root / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
row = next(r for r in rows if r['file'].endswith('/DVDVideoCodecFFmpeg.cpp'))
compiler = None
for source, output in (('/lab/test_qsv_mapped_buffer_private.cpp', '/tmp/test.o'),
                       (str(root / 'xbmc/cores/VideoPlayer/Buffers/VideoBuffer.cpp'), '/tmp/base.o')):
    args = shlex.split(row['command'])
    compiler = args[0]
    args = [a for a in args if not a.startswith('-flto')]
    for i, item in enumerate(args):
        if item == row['file']: args[i] = source
        if item == '-o': args[i + 1] = output
    args += ['-Werror', '-ffunction-sections', '-fdata-sections', '-UNDEBUG']
    subprocess.run(args, cwd=row['directory'], check=True)
subprocess.run([compiler, '/tmp/test.o', '/tmp/base.o', '-lavutil', '-Wl,--gc-sections',
    '-lvpl', '-lva', '-lva-drm', '-lm', '-lpthread', '-ldl', '-o', '/tmp/test'], check=True)
sdk = base / 'toolchain/x86_64-libreelec-linux-gnu/sysroot'
subprocess.run([str(sdk / 'usr/lib/ld-linux-x86-64.so.2'), '--library-path',
                str(sdk / 'usr/lib'), '/tmp/test'], check=True)
