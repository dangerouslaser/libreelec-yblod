"""Strict non-DVBridge objects and partial-link QSV symbol resolution only."""
import json
import os
import pathlib
import shlex
import subprocess
import sys

root, work = map(pathlib.Path, sys.argv[1:3])
rows = json.loads((root / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
env = dict(os.environ, CCACHE_DISABLE='1')
objects = []
compiler = None
for source, original in (('QsvMappedBuffer.cpp', 'VideoBuffer.cpp'),
                         ('VaapiEGL.cpp', 'VaapiEGL.cpp'),
                         ('RendererVAAPIGLES.cpp', 'RendererVAAPIGLES.cpp')):
    row = next(row for row in rows if row['file'].endswith('/' + original))
    args = [arg for arg in shlex.split(row['command'])
            if not arg.startswith(('-DHAVE_DVBRIDGE', '-DHAVE_YBLOD_NATIVE_PLAYBACK'))]
    output = work / ('no-dvbridge-' + source + '.o')
    for i, arg in enumerate(args):
        if arg == row['file']:
            args[i] = str(work / source)
        elif arg == '-o':
            args[i + 1] = str(output)
    args[1:1] = ['-iquote', str(work), '-I' + str(work / 'overrides'),
                 '-iquote', str(pathlib.Path(row['file']).parent)]
    args += ['-Werror']
    subprocess.run(args, cwd=row['directory'], env=env, check=True)
    compiler = next(arg for arg in args if arg.endswith('-g++'))
    objects.append(str(output))
    print('non_dvbridge_strict_object_PASS', source)
combined = work / 'no-dvbridge-partial-link.o'
subprocess.run([compiler, '-r', '-nostdlib', '-flto=1', *objects, '-o', str(combined)],
               env=env, check=True)
nm = str(pathlib.Path(compiler).with_name('x86_64-libreelec-linux-gnu-nm'))
undefined = subprocess.check_output([nm, '-u', str(combined)], text=True)
assert 'CQsvMapped' not in undefined, undefined
print('non_dvbridge_partial_link_qsv_symbols_resolved_PASS')
