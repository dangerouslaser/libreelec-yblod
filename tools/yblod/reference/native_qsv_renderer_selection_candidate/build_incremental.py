import hashlib,json,pathlib,subprocess
ROOT=pathlib.Path('/home/bryan/Projects/libreelec-yblod-reconstruction')
CASE=ROOT/'target/qsv-bl-el-kodi-selection-20261006'
STAGE=ROOT/'target/qsv-renderer-selection-fix-20261006'
def run(args):return subprocess.check_output(args,text=True).strip()
cid=(CASE/'owned.cid').read_text().strip()
old=json.loads(run(['docker','inspect',cid]))[0]
assert not old['State']['Running'] and not old['State']['OOMKilled']
assert old['Image']=='sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e'
source=CASE/'kodi/xbmc/cores/VideoPlayer/VideoRenderers/DVBridgeGLES.cpp'
before=source.read_bytes();after=(STAGE/'DVBridgeGLES.cpp').read_bytes()
assert before.count(b'(qsvFlag && !std::strcmp(qsvFlag, "1") && elRoute != 1))')==1
assert after==before.replace(b'(qsvFlag && !std::strcmp(qsvFlag, "1") && elRoute != 1))',b'(enhancement && qsvFlag && !std::strcmp(qsvFlag, "1") && elRoute != 1))')
(STAGE/'DVBridgeGLES.before.cpp').write_bytes(before)
subprocess.run(['cp',str(STAGE/'DVBridgeGLES.cpp'),str(source)],check=True)
args=['docker','create','--memory=4g','--memory-swap=4g','--cpus=4','--network=none','--read-only','--tmpfs','/tmp:rw,nosuid,exec,size=128m','--user','0:0','-e','CCACHE_DISABLE=1','-e','TMPDIR=/lab/compiler-tmp']
for mount in old['Mounts']:
 if mount['Type']=='bind':args+=['--mount','type=bind,src='+mount['Source']+',dst='+mount['Destination']+('' if mount['RW'] else ',readonly')]
build='/build/build.LibreELEC-Generic.x86_64-13.0-devel'
work=build+'/build/kodi-22.0rc1-Piers/.x86_64-libreelec-linux-gnu'
args+=['--entrypoint','/bin/sh',old['Image'],'-c','export PATH='+build+'/toolchain/bin:$PATH; cd '+work+' && ninja -j4 kodi']
new=run(args);(STAGE/'owned.cid').write_text(new)
print('Build container: '+new,flush=True)
with (STAGE/'build.log').open('x') as log:
 result=subprocess.run(['docker','start','-a',new],stdout=log,stderr=subprocess.STDOUT,timeout=5400)
state=json.loads(run(['docker','inspect',new]))[0]['State']
report={'exit_code':result.returncode,'state':state,'source_sha256':hashlib.sha256(after).hexdigest()}
if result.returncode==0:
 binary=CASE/'kodi/.x86_64-libreelec-linux-gnu/kodi.bin'
 subprocess.run(['cp',str(binary),str(STAGE/'kodi.bin')],check=True)
 report['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
(STAGE/'build-result.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
raise SystemExit(result.returncode)
