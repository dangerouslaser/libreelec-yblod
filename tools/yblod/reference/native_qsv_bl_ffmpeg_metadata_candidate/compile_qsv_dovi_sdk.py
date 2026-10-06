"""Strict disposable object compile using the authoritative SDK recipe."""
import pathlib
import os
import shlex
import subprocess

cgroup = pathlib.Path('/sys/fs/cgroup')
assert int((cgroup / 'memory.max').read_text()) == 536870912
assert int((cgroup / 'memory.swap.max').read_text()) == 0
quota, period = map(int, (cgroup / 'cpu.max').read_text().split())
assert 0 < quota <= period

root = pathlib.Path('/build/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2')
config = {}
for line in (root / 'ffbuild/config.mak').read_text().splitlines():
    if '=' in line:
        name, value = line.split('=', 1)
        config[name] = value
for name in ('CONFIG_GPL', 'CONFIG_VERSION3', 'CONFIG_HEVC_QSV_DECODER', 'CONFIG_DOVI_RPUDEC'):
    source = root / ('config_components.h' if name.endswith('DECODER') else 'config.h')
    assert '#define ' + name + ' 1' in source.read_text(), name
args = shlex.split(config['CC']) + shlex.split(config['CPPFLAGS']) + shlex.split(config['CFLAGS'])
fixture = pathlib.Path(os.environ.get('QSV_DOVI_FIXTURE_ROOT', '/lab'))
args += ['-I' + str(root), '-iquote', str(root / 'libavcodec'), '-Werror',
         '-c', str(fixture / 'qsvdec.c'), '-o', '/tmp/qsvdec.o']
subprocess.run(args, cwd=root, check=True, env={**os.environ, 'CCACHE_DISABLE': '1'})
assert 0 < int((cgroup / 'memory.peak').read_text()) <= 536870912
assert int((cgroup / 'memory.swap.current').read_text()) == 0
assert int((cgroup / 'memory.swap.peak').read_text()) == 0
assert all(int(line.split()[1]) == 0 for line in (cgroup / 'memory.events').read_text().splitlines())
print('strict_authoritative_sdk_qsv_dovi_object_PASS')
