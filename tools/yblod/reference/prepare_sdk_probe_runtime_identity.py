"""Private SDK diagnostic manifest preparation; never probes hardware or media."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from observe_live_el_qsv_probe import code_fingerprint

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sdk',type=Path,required=True)
parser.add_argument('--binary',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
sdk=args.sdk.resolve(strict=True)
library=sdk/'x86_64-libreelec-linux-gnu/sysroot/usr/lib'
gcc=sdk/'x86_64-libreelec-linux-gnu/lib'
if args.output.exists() or args.output.is_symlink():raise ValueError('Fresh private manifest required')
def resolve(path):
    resolved=path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(sdk):raise ValueError('SDK-only code closure required')
    return resolved
roots=[library/name for name in ('ld-linux-x86-64.so.2','libavcodec.so','libavformat.so','libavutil.so','libvpl.so','libmfx-gen.so','dri/iHD_drv_video.so')]
pending=[resolve(path) for path in roots]
binary=args.binary.resolve(strict=True)
initial=subprocess.check_output(['readelf','-d',str(binary)],text=True)
for name in re.findall(r'\(NEEDED\).*?\[([^]]+)\]',initial):
    options=[root/name for root in (library,gcc) if (root/name).exists()]
    if not options:raise ValueError('Probe dependency absent from SDK')
    pending.append(resolve(options[0]))
files={}
while pending:
    path=pending.pop()
    if str(path) in files:continue
    files[str(path)]=dict(path=str(path),sha256=code_fingerprint(path)[1])
    dynamic=subprocess.check_output(['readelf','-d',str(path)],text=True)
    for name in re.findall(r'\(NEEDED\).*?\[([^]]+)\]',dynamic):
        options=[root/name for root in (library,gcc) if (root/name).exists()]
        if not options:raise ValueError('Code dependency absent from SDK')
        pending.append(resolve(options[0]))
with args.output.open('x') as stream:json.dump({'files':files},stream)
args.output.chmod(0o600)
print(json.dumps({'code_file_count':len(files),'code_bytes':sum(Path(path).stat().st_size for path in files),'hardware_access':False}))
