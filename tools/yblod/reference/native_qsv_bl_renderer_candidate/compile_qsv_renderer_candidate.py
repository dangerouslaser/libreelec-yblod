"""Compile disposable source copies with the SDK's actual object commands."""
import json
import pathlib
import shlex
import subprocess
import sys

root, work = map(pathlib.Path, sys.argv[1:3])
rows = json.loads((root / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
for disabled in (False, True):
    for filename in ('VaapiEGL.cpp', 'RendererVAAPIGLES.cpp', 'DVBridgeGLES.cpp'):
        row = next(r for r in rows if r['file'].endswith('/' + filename))
        args = shlex.split(row['command'])
        if disabled:
            args = [a for a in args if not a.startswith('-DHAVE_YBLOD_NATIVE_PLAYBACK')]
        for i, item in enumerate(args):
            if item == row['file']:
                args[i] = str(work / filename)
            if item == '-o':
                args[i + 1] = str(work / (filename + '.o'))
        args[1:1] = ['-iquote', str(work / 'overrides'), '-I' + str(work),
                     '-iquote', str(pathlib.Path(row['file']).parent)]
        args += ['-Werror']
        subprocess.run(args, cwd=row['directory'], check=True)
        print('strict_sdk_object_PASS', filename, 'native=' + str(int(not disabled)))
