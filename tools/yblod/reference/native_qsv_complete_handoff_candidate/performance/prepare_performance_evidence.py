"""Prepare exclusive scalar/code-only manifests for the staged short comparison."""
import hashlib
import json
from pathlib import Path
ROOT=Path('/storage/yblod-qsv-el-aff416-runtime')
CASE=Path('/storage/yblod-bl-el-handoff-runtime-20261006')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
old=json.loads((ROOT/'manifest.json').read_text())
artifacts={}
for name,item in json.loads((CASE/'artifacts-private.json').read_text()).items():
    if not name.startswith('lib'):continue
    path=CASE/'lib'/name
    assert sha(path)==item['sha256']
    artifacts[name]=dict(item,runtime_path=str(path))
for name,item in old['artifacts'].items():
    if not name.startswith(('libvpl.so.','libmfx-gen.so.')):continue
    path=ROOT/'lib'/name
    assert sha(path)==item['sha256']
    artifacts[name]=dict(item,runtime_path=str(path))
runtime=ROOT/'handoff-performance-runtime-manifest-private.json'
with runtime.open('x') as stream:json.dump({'artifacts':artifacts},stream)
pins={}
for directory in (ROOT/'handoff-perf-tools',ROOT/'baseline-tools'):
    for path in sorted(directory.rglob('*')):
        if path.is_file() and path.suffix in ('.py','.conf'):
            assert path.resolve()==path
            pins[str(path)]=sha(path)
for path in (ROOT/'unit_start_barrier3_private.py',ROOT/'run_handoff_performance_private.py',runtime):
    pins[str(path)]=sha(path)
manifest=ROOT/'handoff-performance-tool-pins-private.json'
with manifest.open('x') as stream:json.dump(pins,stream,sort_keys=True)
print(json.dumps({'tool_manifest_sha256':sha(manifest),
    'controller_sha256':sha(ROOT/'run_handoff_performance_private.py'),'pinned_files':len(pins)}))
