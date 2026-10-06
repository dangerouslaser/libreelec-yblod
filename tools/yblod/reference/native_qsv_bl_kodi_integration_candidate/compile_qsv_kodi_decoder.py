"""Strict SDK object check of disposable default-off QSV decoder sources."""
import json
import os
import pathlib
import shlex
import subprocess
import sys

root, work = map(pathlib.Path, sys.argv[1:3])
rows = json.loads((root / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
row = next(r for r in rows if r['file'].endswith('/DVDVideoCodecFFmpeg.cpp'))
for enabled in (True, False):
    args = shlex.split(row['command'])
    if not enabled:
        args = [arg for arg in args if not arg.startswith('-DHAVE_DVBRIDGE')]
    for i, arg in enumerate(args):
        if arg == row['file']:
            args[i] = str(work / 'DVDVideoCodecFFmpeg.cpp')
        elif arg == '-o':
            args[i + 1] = str(work / ('decoder-' + str(int(enabled)) + '.o'))
    args[1:1] = ['-iquote', str(work), '-I' + str(work / 'overrides'),
                 '-iquote', str(pathlib.Path(row['file']).parent)]
    args.append('-Werror')
    env = dict(os.environ, CCACHE_DISABLE='1')
    subprocess.run(args, cwd=row['directory'], env=env, check=True)
    print('strict_sdk_decoder_object_PASS', 'dvbridge=' + str(int(enabled)))
