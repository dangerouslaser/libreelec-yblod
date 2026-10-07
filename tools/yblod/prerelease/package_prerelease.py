#!/usr/bin/env python3
"""Package a pinned, tested runtime into a copy of its matching LibreELEC OS.

No host block devices, original images, stable update channel or SDK are modified.
Run in a 4 GiB, no-swap systemd scope. Requires squashfs-tools and SDK mtools.
"""
import argparse,gzip,hashlib,json,os,re,shutil,struct,subprocess,tarfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--public',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();public=a.public.resolve();sdk=a.sdk.resolve();out=a.output.absolute()
assert os.geteuid()==0, 'Root required to preserve protected stock OS files while packaging'
assert out.parent.resolve()==public/'target' and out.name=='release-yblod-0.2-pre1'
assert not out.exists();out.mkdir()
stem='LibreELEC-Generic.x86_64-13.0-yblod-0.2-pre1'
base=sdk/'target/LibreELEC-Generic.x86_64-13.0-yblod-0.1-direct-test4'
build=sdk/'build.LibreELEC-Generic.x86_64-13.0-devel'
sysroot=build/'toolchain/x86_64-libreelec-linux-gnu/sysroot'
kodi=public/'target/qsv-bl-el-kodi-selection-20261006/kodi'
ffmpeg=public/'target/qsv-bl-keyflag-library-handoff-20261006/ffmpeg-bl-qsv-candidate'
runtime_input=public/'target/release-yblod-0.2-runtime-input'
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def run(*args,**kw):
 print(' '.join(map(str,args)),flush=True)
 return subprocess.run(list(map(str,args)),check=True,**kw)
assert shutil.disk_usage(out).free>10*1024**3
assert sha(str(base)+'.system')=='86145b4b238611d966c333fbccdcec2a3a43397da23cbac13f441fde80ad412c'
assert sha(str(base)+'.kernel')=='b22fd13f1a4f1e4a6f063279755b6c96d75f65ac10d11a76487f76aa6e4e1d9e'
binary=public/'target/qsv-renderer-selection-fix-20261006/kodi.bin'
assert sha(binary)=='14f96e58da6f72274c0e9eac368bfa165795506d18126b287bd0f14f5e2517cb'
root=out/'rootfs'
run('unsquashfs','-processors','4','-d',root,str(base)+'.system')
runtime=root/'usr/lib/yblod/runtime';runtime.mkdir(parents=True)
pins=json.loads(Path(__file__).with_name('ffmpeg-artifacts.json').read_text())
files={}
for name,item in pins.items():
 if name=='kodi.bin':continue
 src=runtime_input/name
 assert sha(src)==item['sha256'],name
 shutil.copyfile(src,runtime/name);os.chmod(runtime/name,0o755)
 files['usr/lib/yblod/runtime/'+name]=item['sha256']
for name,expected in [('libvpl.so.2.17','299c300702dff1464781bbaba3cb6037bd8ddabdfd9241708a9ba877baca02d0'),('libmfx-gen.so.1.2.17','a0e2acafa74214e7d6247dca26168a0814a51065aa08d09e99ad0990c3baf13c')]:
 src=sysroot/'usr/lib'/name;assert sha(src)==expected
 shutil.copyfile(src,runtime/name);os.chmod(runtime/name,0o755);files['usr/lib/yblod/runtime/'+name]=expected
for name,target in {'libvpl.so.2':'libvpl.so.2.17','libvpl.so':'libvpl.so.2.17','libmfx-gen.so.1.2':'libmfx-gen.so.1.2.17','libmfx-gen.so':'libmfx-gen.so.1.2.17'}.items():(runtime/name).symlink_to(target)
shutil.copyfile(binary,root/'usr/lib/kodi/kodi.bin');os.chmod(root/'usr/lib/kodi/kodi.bin',0o755)
files['usr/lib/kodi/kodi.bin']=sha(binary)
conf=root/'usr/lib/kodi/kodi.conf'
flags={'DVBRIDGE_NATIVE_RECONSTRUCTION':'1','DVBRIDGE_NATIVE_DIAGNOSTICS':'1','DVBRIDGE_NATIVE_FP32':'1','DVBRIDGE_NATIVE_COLOUR_NO_REIMPORT':'1','DVBRIDGE_NATIVE_NLQ_LUT':'1','DVBRIDGE_NATIVE_PACKED_OUTPUT':'1','DVBRIDGE_NATIVE_PLANAR_OUTPUT':'1','DVBRIDGE_NATIVE_BATCHED_PLANES':'0','DVBRIDGE_NATIVE_IMMUTABLE_INSTRUCTIONS':'0','DVBRIDGE_CAPTURE_OUTPUTS':'0','DVBRIDGE_CAPTURE_PAIRS':'0','DVBRIDGE_FEL_QSV':'1','DVBRIDGE_BASE_QSV':'1','LD_LIBRARY_PATH':'/usr/lib/yblod/runtime','ONEVPL_PRIORITY_PATH':'/usr/lib/yblod/runtime'}
conf.write_text(conf.read_text()+'\n# yblod 0.2 prerelease: tested Profile 7 dual-QSV route\n'+''.join(k+'='+v+'\n' for k,v in flags.items()))
launcher=root/'usr/lib/kodi/kodi.sh';text=launcher.read_text();line='/usr/lib/kodi/kodi.bin $SAVED_ARGS'
assert text.count(line)==1
launcher.write_text(text.replace(line,'LD_LIBRARY_PATH=/usr/lib/yblod/runtime:$LD_LIBRARY_PATH ONEVPL_PRIORITY_PATH=/usr/lib/yblod/runtime '+line));os.chmod(launcher,0o755)
service=root/'usr/lib/systemd/system/kodi.service.d';service.mkdir(exist_ok=True)
(service/'yblod-prerelease.conf').write_text('[Service]\nLimitCORE=256M\n')
revision=subprocess.check_output(['git','-c','safe.directory='+str(public),'-C',str(public),'rev-parse','HEAD'],text=True).strip()
osrelease=root/'etc/os-release';text=osrelease.read_text().replace('yblod-0.1-direct-test4','yblod-0.2-pre1');text=re.sub(r'^BUILD_ID="[^"]+"',f'BUILD_ID="{revision}"',text,flags=re.M);osrelease.write_text(text)
if (root/'etc/release').exists():(root/'etc/release').write_text('LibreELEC (yblod): yblod-0.2-pre1\n')
manifest={'version':'0.2-pre1','source_commit':revision,'packaging':'Pinned direct-test4 OS + exact tested Kodi/FFmpeg/VPL runtime; not a fresh full OS rebuild','base_system_sha256':sha(str(base)+'.system'),'base_kernel_sha256':sha(str(base)+'.kernel'),'runtime_files':files,'environment':flags,'el_scaling':'Intel VAAPI media-engine bilinear; not proven nearest-neighbour','n100_validated':False,'native_reconstruction_scope':'Profile 7 FEL; other supported streams use existing route'}
(out/'RUNTIME-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
(root/'usr/share/yblod').mkdir(exist_ok=True);shutil.copyfile(out/'RUNTIME-MANIFEST.json',root/'usr/share/yblod/runtime-manifest.json')
system=out/(stem+'.system')
run('mksquashfs',root,system,'-noappend','-comp','zstd','-Xcompression-level','19','-b','1048576','-processors','4','-mem','512M','-no-xattrs','-all-root')
for name,expected in files.items():
 result=subprocess.check_output(['unsquashfs','-cat',str(system),name]);assert hashlib.sha256(result).hexdigest()==expected,name
kernel=out/(stem+'.kernel');shutil.copyfile(str(base)+'.kernel',kernel)
bundle=out/stem;bundle.mkdir();target=bundle/'target';target.mkdir()
for name,src in [('SYSTEM',system),('KERNEL',kernel)]:
 shutil.copyfile(src,target/name)
 (target/(name+'.md5')).write_text(hashlib.md5(src.read_bytes()).hexdigest()+'  target/'+name+'\n')
(bundle/'RELEASE').write_text('Generic.x86_64-yblod-0.2-pre1\nKodi commit: 22.0rc1-Piers\n')
notes=Path(__file__).with_name('RELEASE-NOTES.md').read_text();(bundle/'README.md').write_text(notes);(bundle/'CHANGELOG').write_text(notes)
with tarfile.open(str(base)+'.tar') as old:
 for item in old.getmembers():
  suffix=item.name.split('/',1)[1] if '/' in item.name else ''
  if not suffix.startswith('licenses/'):continue
  dest=bundle/suffix;assert dest.is_relative_to(bundle)
  if item.isdir():dest.mkdir(parents=True,exist_ok=True)
  elif item.isfile():dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old.extractfile(item).read())
shutil.copyfile(out/'RUNTIME-MANIFEST.json',bundle/'RUNTIME-MANIFEST.json')
archive=out/(stem+'.tar')
with tarfile.open(archive,'w') as tar:tar.add(bundle,arcname=stem)
# Rewrite files only inside a newly decompressed image, never a host block device.
image=out/(stem+'.img')
with gzip.open(str(base)+'.img.gz','rb') as src,image.open('xb') as dst:shutil.copyfileobj(src,dst,1048576)
with image.open('rb') as stream:mbr=stream.read(512)
assert mbr[510:]==b'\x55\xaa'
table=json.loads(subprocess.check_output(['sfdisk','--json',str(image)]))['partitiontable']
assert table['unit']=='sectors' and table.get('sectorsize',512)==512
part=table['partitions'][0]
assert part['type'].lower() in ('b','c','e','6','c12a7328-f81f-11d2-ba4b-00a0c93ec93b','ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
sector=part['start'];assert sector>=2048
fat=str(image)+'@@'+str(sector*512);mcopy=build/'toolchain/bin/mcopy';mdir=build/'toolchain/bin/mdir'
run(mdir,'-i',fat,'::/')
for name,src in [('SYSTEM',system),('KERNEL',kernel),('SYSTEM.md5',target/'SYSTEM.md5'),('KERNEL.md5',target/'KERNEL.md5')]:run(mcopy,'-o','-i',fat,src,'::/'+name)
run(mdir,'-i',fat,'::/')
for name,expected in [('SYSTEM',sha(system)),('KERNEL',sha(kernel))]:
 check=out/('image-check-'+name);run(mcopy,'-i',fat,'::/'+name,check);assert sha(check)==expected
compressed=out/(stem+'.img.gz')
with image.open('rb') as src,compressed.open('xb') as dst:
 with gzip.GzipFile(filename='',mode='wb',fileobj=dst,mtime=0,compresslevel=6) as gz:shutil.copyfileobj(src,gz,1048576)
# Complete modified source trees, excluding generated objects and private test data.
sources=out/'yblod-0.2-pre1-playback-sources.tar.gz'
trees={'kodi-22.0rc1-Piers':kodi,'ffmpeg-9.0.2':ffmpeg,'libvpl-2.17.0':build/'build/libvpl-2.17.0','vpl-gpu-rt-26.3.5':build/'build/vpl-gpu-rt-26.3.5'}
def source_filter(item):
 parts=Path(item.name).parts
 if any(x.startswith(('.x86_64-','.git')) or x in ('__pycache__','CMakeFiles') for x in parts):return None
 if re.search(r'\.(o|a|so)(\.|$)',item.name) or item.name.endswith(('.pyc','.bin')):return None
 if item.issym() and item.linkname.startswith('/'):return None
 return item
with tarfile.open(sources,'w:gz') as tar:
 for name,directory in trees.items():tar.add(directory,arcname=name,filter=source_filter)
 tar.add(Path(__file__),arcname='packaging/package_prerelease.py')
 tar.add(Path(__file__).with_name('ffmpeg-artifacts.json'),arcname='packaging/ffmpeg-artifacts.json')
 tar.add(Path(__file__).with_name('RELEASE-NOTES.md'),arcname='packaging/RELEASE-NOTES.md')
assets=[archive,compressed,sources,out/'RUNTIME-MANIFEST.json']
for asset in assets:(out/(asset.name+'.sha256')).write_text(sha(asset)+'  '+asset.name+'\n')
(out/'SHA256SUMS').write_text(''.join(sha(x)+'  '+x.name+'\n' for x in assets))
print(json.dumps({'packaging_complete':True,'assets':[x.name for x in assets],'system_sha256':sha(system),'kernel_sha256':sha(kernel)},indent=2),flush=True)
