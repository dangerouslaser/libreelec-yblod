"""Finish the copied GPT image/source artifacts after SYSTEM/update construction."""
import ast,gzip,hashlib,json,os,re,shutil,subprocess,tarfile
from pathlib import Path
public=Path('/home/bryan/Projects/libreelec-yblod-reconstruction');sdk=Path('/home/bryan/Projects/libreelec-yblod');out=public/'target/release-yblod-0.2-pre1'
stem='LibreELEC-Generic.x86_64-13.0-yblod-0.2-pre1';image=out/(stem+'.img');system=out/(stem+'.system');kernel=out/(stem+'.kernel');build=sdk/'build.LibreELEC-Generic.x86_64-13.0-devel'
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def run(*args):return subprocess.run(list(map(str,args)),check=True)
assert os.geteuid()==0 and image.is_file() and system.is_file() and kernel.is_file()
assert not (out/(stem+'.img.gz')).exists()
table=json.loads(subprocess.check_output(['sfdisk','--json',str(image)]))['partitiontable'];part=table['partitions'][0]
assert table['unit']=='sectors' and table.get('sectorsize',512)==512
assert part['type'].lower() in ('b','c','e','6','c12a7328-f81f-11d2-ba4b-00a0c93ec93b','ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
assert part['start']>=2048
fat=str(image)+'@@'+str(part['start']*512);mcopy=build/'toolchain/bin/mcopy';mdir=build/'toolchain/bin/mdir'
run(mdir,'-i',fat,'::/')
for name,src in [('SYSTEM',system),('KERNEL',kernel),('SYSTEM.md5',out/stem/'target/SYSTEM.md5'),('KERNEL.md5',out/stem/'target/KERNEL.md5')]:run(mcopy,'-o','-i',fat,src,'::/'+name)
for name,expected in [('SYSTEM',sha(system)),('KERNEL',sha(kernel))]:
 check=out/('image-check-'+name);run(mcopy,'-i',fat,'::/'+name,check);assert sha(check)==expected
compressed=out/(stem+'.img.gz')
with image.open('rb') as src,compressed.open('xb') as dst:
 with gzip.GzipFile(filename='',mode='wb',fileobj=dst,mtime=0,compresslevel=6) as gz:shutil.copyfileobj(src,gz,1048576)
print('Verified copied GPT USB image complete',flush=True)
def source_filter(item):
 parts=Path(item.name).parts
 if any(x.startswith(('.x86_64-','.git')) or x in ('__pycache__','CMakeFiles') for x in parts):return None
 if re.search(r'\.(o|a|so)(\.|$)',item.name) or item.name.endswith(('.pyc','.bin')):return None
 if item.issym() and item.linkname.startswith('/'):return None
 return item
trees={'kodi-22.0rc1-Piers':public/'target/qsv-bl-el-kodi-selection-20261006/kodi','ffmpeg-9.0.2':public/'target/qsv-bl-keyflag-library-handoff-20261006/ffmpeg-bl-qsv-candidate','libvpl-2.17.0':build/'build/libvpl-2.17.0','vpl-gpu-rt-26.3.5':build/'build/vpl-gpu-rt-26.3.5'}
sources=out/'yblod-0.2-pre1-playback-sources.tar.gz'
assert not sources.exists()
with tarfile.open(sources,'w:gz') as tar:
 for name,directory in trees.items():tar.add(directory,arcname=name,filter=source_filter)
 for name in ('package_prerelease.py','finish_artifacts.py','ffmpeg-artifacts.json','RELEASE-NOTES.md'):tar.add(public/'tools/yblod/prerelease'/name,arcname='packaging/'+name)
with tarfile.open(sources) as tar:assert 'ffmpeg-9.0.2/ffbuild/common.mak' in tar.getnames()
assets=[out/(stem+'.tar'),compressed,sources,out/'RUNTIME-MANIFEST.json']
for asset in assets:(out/(asset.name+'.sha256')).write_text(sha(asset)+'  '+asset.name+'\n')
(out/'SHA256SUMS').write_text(''.join(sha(x)+'  '+x.name+'\n' for x in assets))
print(json.dumps({'packaging_complete':True,'assets':[{'name':x.name,'bytes':x.stat().st_size,'sha256':sha(x)} for x in assets]},indent=2),flush=True)
