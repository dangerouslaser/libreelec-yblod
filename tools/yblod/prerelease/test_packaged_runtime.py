"""Short P7/P8 smoke test of the installed prerelease, with no captures."""
import hashlib,json,re,sys,time,urllib.request
from pathlib import Path
CASE=Path('/storage/yblod-prerelease-validation-20261006');CASE.mkdir(exist_ok=True)
def rpc(method,params=None):
 data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode()
 value=json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/jsonrpc',data,{'Content-Type':'application/json'}),timeout=5))
 if 'error' in value:raise RuntimeError(value['error'])
 return value['result']
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def identity():
 pids=[p for p in Path('/proc').iterdir() if p.name.isdigit() and (p/'comm').exists() and (p/'comm').read_text().strip()=='kodi.bin']
 assert len(pids)==1
 return {'pid':int(pids[0].name),'binary_sha256':sha(pids[0]/'exe')}
result={'pass':False,'cases':[]};player=None
try:
 assert 'VERSION="yblod-0.2-pre1"' in Path('/etc/os-release').read_text()
 assert not any(row.split()[4]=='/usr/lib/kodi/kodi.bin' for row in Path('/proc/self/mountinfo').read_text().splitlines())
 assert not Path('/run/systemd/system/kodi.service.d/yblod-native-playback.conf').exists()
 stable=None
 for i in range(60):
  try:
   ready=rpc('Player.GetActivePlayers')==[] and rpc('GUI.GetProperties',{'properties':['currentwindow']})['currentwindow']['id'] in (10000,10025)
  except (OSError,RuntimeError):ready=False
  if ready:
   if stable is None:stable=time.monotonic()
   if time.monotonic()-stable>=10:break
  else:stable=None
  time.sleep(1)
 else:raise RuntimeError('menu readiness timeout')
 initial=identity();assert initial['binary_sha256']=='14f96e58da6f72274c0e9eac368bfa165795506d18126b287bd0f14f5e2517cb'
 manifest=json.loads(Path('/usr/share/yblod/runtime-manifest.json').read_text())
 for movie,title,profile in [(3391,'Saving Private Ryan',7),(20,'12 Angry Men',8)]:
  assert rpc('VideoLibrary.GetMovieDetails',{'movieid':movie,'properties':['title']})['moviedetails']['title']==title
  log=Path('/storage/.kodi/temp/kodi.log');offset=log.stat().st_size
  rpc('Player.Open',{'item':{'movieid':movie},'options':{'resume':False}})
  for i in range(25):
   active=[x for x in rpc('Player.GetActivePlayers') if x['type']=='video']
   if active:player=active[0]['playerid'];break
   time.sleep(1)
  assert player is not None
  samples=[]
  for i in range(15):
   time.sleep(2)
   props=rpc('Player.GetProperties',{'playerid':player,'properties':['time','speed']});assert props['speed']==1
   t=props['time'];samples.append(3600*t['hours']+60*t['minutes']+t['seconds']+t['milliseconds']/1000)
  assert samples[-1]-samples[0]>25 and identity()==initial
  decoder=rpc('XBMC.GetInfoLabels',{'labels':['Player.Process(videodecoder)']})['Player.Process(videodecoder)']
  with log.open('rb') as f:f.seek(offset);text=f.read().decode(errors='replace')
  assert f'profile={profile} ' in text and 'DVBridge first frame:' in text
  assert 'could not open video codec' not in text and 'DVBridge renderer: stage=' not in text
  health=[dict(re.findall(r'([a-z_]+)=([^\s]+)',row)) for row in text.splitlines() if 'DVBridge playback health:' in row]
  assert len(health)>=3 and all(x.get('stalled')=='false' for x in health)
  assert sum(int(x.get('output_attempts','0')) for x in health)>400
  assert max(int(x['drop_total']) for x in health)==0
  if profile==7:
   assert re.search(r'DVBridge BL QSV: decoder=hevc_qsv metadata=1 mapped=[1-9]\d*',text)
   assert 'DV FEL decoder: qsv_selected=1' in text
  else:assert 'vaapi' in decoder and 'DVBridge BL QSV:' not in text
  loaded={}
  for row in (Path('/proc')/str(initial['pid'])/'maps').read_text().splitlines():
   fields=row.split(None,5)
   if len(fields)==6 and fields[5].startswith('/usr/lib/yblod/runtime/'):
    path=Path(fields[5]);loaded[path.name]=sha(path)
    assert loaded[path.name]==manifest['runtime_files'][str(path)[1:]]
  assert 'libavcodec.so.63' in loaded and 'libavutil.so.61' in loaded
  if profile==7:assert 'libvpl.so.2.17' in loaded and 'libmfx-gen.so.1.2.17' in loaded
  rpc('Player.Stop',{'playerid':player});player=None
  for i in range(20):
   if rpc('Player.GetActivePlayers')==[]:break
   time.sleep(1)
  else:raise RuntimeError('stop timeout')
  case={'title':title,'profile':profile,'decoder':decoder,'timeline_advance_seconds':samples[-1]-samples[0],'stalls':False,'drops':0,'skips_max':max(int(x['skip_total']) for x in health),'output_attempts':sum(int(x.get('output_attempts','0')) for x in health),'runtime_loaded_sha256':loaded}
  result['cases'].append(case);print(json.dumps(case),flush=True)
  time.sleep(3)
 result.update({'pass':True,'installed_version':'0.2-pre1','temporary_overrides_absent':True,'identity':initial,'idle':rpc('Player.GetActivePlayers')==[],'scope':'Short VM decoder/renderer smoke checks; not TV visual or N100 validation'})
except BaseException as e:
 result['error']=str(e);result['error_type']=type(e).__name__
 if player is not None:
  try:rpc('Player.Stop',{'playerid':player})
  except BaseException:pass
finally:
 (CASE/'PACKAGED-RUNTIME-TEST.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
raise SystemExit(0 if result['pass'] else 1)
