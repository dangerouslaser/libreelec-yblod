"""Make-only continuation of the exact reviewed private configure result."""
import json
import os
import pathlib
import re
import signal
import subprocess
import time
import build_isolated_qsv_bl_ffmpeg as build

ROOT = pathlib.Path('/lab')
WORK = ROOT / 'ffmpeg-bl-qsv-candidate'
SDK = pathlib.Path('/build')
CONFIG = {
    'ffbuild/config.mak': 'accdbb733dfd890d3b8e567104d4c1fde0bfd48a5e23596dfe226b278a0d16c6',
    'config.h': 'bb8dbe51fe7071fd4e7f2e3adb2b749c69b69eff1149fda54f42aa9dae93f652',
    'config_components.h': '29b975a2643e3c3c48526f5991b62f8ab4e29b9935474d43d13f4d7a6206da4c',
}
NATIVE = ('libavcodec/hevc/hevcdec.c', 'libavcodec/hevc/parser.c',
          'libavcodec/dovi_rpudec.c', 'libavcodec/dovi_rpu.c',
          'libavcodec/h2645_parse.c', 'libavcodec/vaapi_hevc.c',
          'libavcodec/version_major.h', 'libavutil/version.h',
          'libavformat/version_major.h', 'libavfilter/version_major.h')

def check_sources():
    source = SDK / build.FFMPEG
    for name, expected in build.GUARDS.items():
        assert build.digest(source / name) == expected
    for name, expected in CONFIG.items():
        assert build.digest(WORK / name) == expected
    assert build.digest(WORK / 'configure') == '7abcd38af3a96b29f440e969dd8ac369ecfbbdec17f3a664e287c74874e3dba5'
    assert build.digest(WORK / 'libavcodec/qsvdec.c') == 'bd88929d56c2105d1f9987c23b343c4b8fd468105b0b319061a105f885217226'
    assert build.digest(WORK / 'libavcodec/qsv_dovi.h') == 'c7a409ec09971a745fbba8b5d87e14e770d501e8ef8f57a232029415f8254293'
    for name in NATIVE:
        assert build.digest(WORK / name) == build.digest(source / name), name
    return {name: build.digest(WORK / name) for name in NATIVE}

def main():
    build.limits()
    assert build.digest(ROOT / 'isolated-ffmpeg-build-results.json') == \
        '01d68c3ff7762745fbedb425ea5242a2d77953b620049e63681f0a3007226115'
    prior = json.loads((ROOT / 'isolated-ffmpeg-build-results.json').read_text())
    assert prior['configuration_completed'] is True and prior['build_completed'] is False
    assert prior['sdk_sources_unchanged'] is True
    assert prior['all_original_enabled_configuration_macros_preserved'] is True
    assert prior['patch_sha256'] == build.PATCHES
    assert not (ROOT / 'isolated-ffmpeg-make-results.json').exists()
    native = check_sources()
    available = next(int(line.split()[1]) * 1024 for line in
                     pathlib.Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    assert available >= 6442450944
    toolchain = SDK / 'build.LibreELEC-Generic.x86_64-13.0-devel/toolchain'
    sysroot = toolchain / 'x86_64-libreelec-linux-gnu/sysroot'
    env = dict(os.environ, CCACHE_DISABLE='1',
               PATH=str(toolchain / 'bin') + ':' + str(toolchain / 'sbin') + ':' + os.environ['PATH'],
               PKG_CONFIG=str(toolchain / 'bin/pkg-config'), PKG_CONFIG_PATH='',
               PKG_CONFIG_LIBDIR=str(sysroot / 'usr/lib/pkgconfig') + ':' + str(sysroot / 'usr/share/pkgconfig'),
               PKG_CONFIG_SYSROOT_BASE=str(toolchain.parent), PKG_CONFIG_SYSROOT_DIR=str(sysroot),
               PKG_CONFIG_ALLOW_SYSTEM_CFLAGS='1', PKG_CONFIG_ALLOW_SYSTEM_LIBS='1')
    process = None
    max_workers = 0
    try:
        process = subprocess.Popen(['make', '-j1'], cwd=WORK, env=env, start_new_session=True)
        deadline = time.monotonic() + 14400
        while process.poll() is None:
            names = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
            workers = sum(bool(re.fullmatch(r'lto1(?:-ltrans)?', name.strip())) for name in names)
            max_workers = max(max_workers, workers)
            assert workers <= 1 and time.monotonic() < deadline
            time.sleep(1)
        assert process.returncode == 0
    finally:
        build.terminate(process)
    assert native == check_sources()
    libraries = {}
    for path in sorted(WORK.glob('lib*/lib*.so.*')):
        if path.is_file() and not path.is_symlink():
            libraries[str(path.relative_to(WORK))] = {'sha256': build.digest(path),
                                                    'bytes': path.stat().st_size}
    assert libraries and any(name.startswith('libavcodec/') for name in libraries)
    result = {'schema': 'yblod.qsv-bl-isolated-make.v1', 'build_completed': True,
              'runtime_qualified': False, 'sdk_sources_unchanged': True,
              'configuration_sha256': CONFIG, 'native_source_and_abi_sha256': native,
              'libraries': libraries, 'ltrans_workers_max_observed': max_workers,
              'resources': build.resources()}
    with (ROOT / 'isolated-ffmpeg-make-results.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'build_completed': True, 'sdk_sources_unchanged': True,
                      'runtime_qualified': False}))

if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError('Private make interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        main()
    except BaseException as error:
        cg = pathlib.Path('/sys/fs/cgroup')
        result = {'schema': 'yblod.qsv-bl-isolated-make-failure.v1',
                  'build_completed': False, 'error_type': type(error).__name__,
                  'runtime_qualified': False,
                  'resources': {name: (cg / name).read_text().strip() for name in
                                ('memory.peak', 'memory.events', 'memory.swap.current',
                                 'memory.swap.peak')}}
        with (ROOT / 'isolated-ffmpeg-make-failure.json').open('x') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        raise
