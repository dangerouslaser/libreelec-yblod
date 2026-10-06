import json
import shlex
import subprocess
from pathlib import Path
root = Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/kodi-22.0rc1-Piers')
rows = json.loads((root / '.x86_64-libreelec-linux-gnu/compile_commands.json').read_text())
row = next(r for r in rows if r['file'].endswith('/DVDVideoCodecFFmpeg.cpp'))
args = shlex.split(row['command'])
for i, item in enumerate(args):
    if item == row['file']: args[i] = '/lab/QsvMappedBuffer.cpp'
    if item == '-o': args[i + 1] = '/tmp/QsvMappedBuffer.o'
args += ['-Werror']
subprocess.run(args, cwd=row['directory'], check=True)
print('mapped_buffer_sdk_object_PASS')
