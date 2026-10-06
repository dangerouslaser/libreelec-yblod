"""Use the actual SDK command; compile private adapter native and non-native."""
import json
from pathlib import Path
import shlex
import subprocess

build=Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/kodi-22.0rc1-Piers/.x86_64-libreelec-linux-gnu')
entries=json.loads((build/'compile_commands.json').read_text())
matches=[item for item in entries if Path(item['file']).name=='DVBridgeGLES.cpp']
if len(matches)!=1: raise SystemExit('Expected exactly one actual bridge command')
command=shlex.split(matches[0]['command'])
command[command.index('-c')+1]='/lab/DVBridgeGLES.cpp'
command[command.index('-o')+1]='/lab/bin/DVBridgeGLES.native.o'
command.insert(1,'-I/lab')
command+=['-iquote',str(Path(matches[0]['file']).parent),'-fno-lto','-Werror']
subprocess.run(command,cwd=build,check=True)
print('Kodi native LUT adapter strict SDK compile PASS',flush=True)
command=[item for item in command if item!='-DHAVE_YBLOD_NATIVE_PLAYBACK=1']
command[command.index('-o')+1]='/lab/bin/DVBridgeGLES.non-native.o'
subprocess.run(command,cwd=build,check=True)
print('Kodi non-native adapter strict SDK compile PASS',flush=True)
for field in ('memory.peak','memory.events','memory.swap.current'):
    print(field+': '+(Path('/sys/fs/cgroup')/field).read_text(),flush=True)
