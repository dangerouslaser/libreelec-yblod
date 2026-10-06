import os,pathlib,shlex,subprocess
root=pathlib.Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2')
cg=pathlib.Path('/sys/fs/cgroup')
assert int((cg/'memory.max').read_text())==536870912 and int((cg/'memory.swap.max').read_text())==0
quota,period=(cg/'cpu.max').read_text().split();assert quota!='max' and 0<int(quota)<=int(period)
cfg=dict(line.split('=',1) for line in (root/'ffbuild/config.mak').read_text().splitlines() if '=' in line)
base=shlex.split(cfg['CC'])+shlex.split(cfg['CPPFLAGS'])+shlex.split(cfg['CFLAGS'])
for mode in ('on','off'):
 d=pathlib.Path('/tmp')/mode;d.mkdir()
 text=(root/'config.h').read_text()
 if mode=='off':text=text.replace('#define CONFIG_GPL 1','#define CONFIG_GPL 0').replace('#define CONFIG_VERSION3 1','#define CONFIG_VERSION3 0')
 (d/'config.h').write_text(text)
 args=base+['-I'+str(d),'-I'+str(root),'-iquote',str(root/'libavcodec'),'-Werror','-c','/candidate/qsvdec.c','-o','/tmp/'+mode+'.o']
 subprocess.run(args,cwd=root,check=True,env={**os.environ,'CCACHE_DISABLE':'1'},timeout=90)
 print('strict SDK feature '+mode+' object PASS')
assert 0<int((cg/'memory.peak').read_text())<=536870912
assert int((cg/'memory.swap.peak').read_text())==0
assert all(int(l.split()[1])==0 for l in (cg/'memory.events').read_text().splitlines())
print('memory_peak='+str(int((cg/'memory.peak').read_text())))
