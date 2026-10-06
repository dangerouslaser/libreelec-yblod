"""Prepare/build a private FFmpeg copy; never write the mounted SDK."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import time
import fnmatch

FFMPEG = 'build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2'
GUARDS = {
    'configure': 'ca57b961b55711e417c4d93123ca70cc56650f3005e747ce36531e7ab5d4043e',
    'libavcodec/qsvdec.c': '94187d5bf29fa060daac741cf12d9f9c99abee3b1f2b93ebc5fe3375369d5f4f',
}
PATCHES = {
    'qsv-bl-metadata-source-only.patch':
        'ef079ad0f9ac273babbbad1db7a74e42c8bcf75b64b5c84adb20b013bcec009f',
    'qsv-bl-metadata-real-init-fix.patch':
        'eaa6a505e8ab852eb42262ff12fc7d22a7146163a7d22cf563ec1f8e3d67795a',
}

def copy_source(source, dest):
    with open(source, 'rb') as incoming, open(dest, 'wb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1048576)
        outgoing.flush()
        os.fsync(outgoing.fileno())
        os.posix_fadvise(incoming.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        os.posix_fadvise(outgoing.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    shutil.copystat(source, dest)
    return dest

def ignore_artifacts(directory, names):
    return [name for name in names if any(fnmatch.fnmatch(name, pattern)
            for pattern in ('*.o', '*.d', '*.a', '*.so', '*.so.*'))]

def terminate(process):
    if process and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

def run_owned(command, work, timeout, env=None):
    process = subprocess.Popen(command, cwd=work, env=env, start_new_session=True)
    try:
        assert process.wait(timeout=timeout) == 0
    finally:
        terminate(process)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def limits():
    cg = pathlib.Path('/sys/fs/cgroup')
    assert int((cg / 'memory.max').read_text()) == 4294967296
    assert int((cg / 'memory.swap.max').read_text()) == 0
    quota, period = map(int, (cg / 'cpu.max').read_text().split())
    assert 0 < quota <= period
    assert not pathlib.Path('/dev/dri').exists()

def resources():
    cg = pathlib.Path('/sys/fs/cgroup')
    events = dict((k, int(v)) for k, v in
                  (line.split() for line in (cg / 'memory.events').read_text().splitlines()))
    peak = int((cg / 'memory.peak').read_text())
    assert 0 < peak <= 4294967296 and not any(events.values())
    assert int((cg / 'memory.swap.current').read_text()) == 0
    assert int((cg / 'memory.swap.peak').read_text()) == 0
    return {'memory_peak_bytes': peak, 'memory_events': events,
            'memory_swap_current_bytes': 0, 'memory_swap_peak_bytes': 0}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sdk', type=pathlib.Path, required=True)
    ap.add_argument('--patch-dir', type=pathlib.Path, required=True)
    ap.add_argument('--work', type=pathlib.Path, required=True)
    ap.add_argument('--prepare', action='store_true')
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--configure', action='store_true')
    args = ap.parse_args()
    source = args.sdk.resolve() / FFMPEG
    assert source.is_dir()
    for name, expected in GUARDS.items():
        assert digest(source / name) == expected, name
    work = args.work.resolve()
    assert str(work).startswith('/lab/') and work.name == 'ffmpeg-bl-qsv-candidate'
    assert not work.exists(), 'Fresh private work directory required; no deletion supported'
    patches = [args.patch_dir / name for name in PATCHES]
    assert all(p.is_file() and digest(p) == PATCHES[p.name] for p in patches)
    if not args.prepare:
        print(json.dumps({'dry_run': True, 'source_guards_passed': True,
                          'sdk_writes': False, 'work_writes': False}))
        return
    limits()
    available = next(int(line.split()[1]) * 1024 for line in
                     pathlib.Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    assert available >= 6442450944, 'At least 6GiB host MemAvailable required'
    shutil.copytree(source, work, symlinks=True, copy_function=copy_source,
                    ignore=ignore_artifacts)
    # Only the newly created private copy is cleaned.
    run_owned(['make', '-j1', 'distclean'], work, 120)
    before = {name: digest(source / name) for name in GUARDS}
    for patch in patches:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())],
                       cwd=work, check=True)
    assert digest(work / 'libavcodec/qsvdec.c') == \
        'bd88929d56c2105d1f9987c23b343c4b8fd468105b0b319061a105f885217226'
    configuration = next(line.split('=', 1)[1] for line in
                         (source / 'ffbuild/config.mak').read_text().splitlines()
                         if line.startswith('FFMPEG_CONFIGURATION='))
    command = shlex.split(configuration)
    assert '--enable-libvpl' in command and '--enable-gpl' in command and '--enable-version3' in command
    assert '--enable-shared' in command and '--disable-programs' in command
    # Isolated prefix prevents any install target from writing the SDK/sysroot.
    assert not any(arg.startswith('--srcdir=') for arg in command)
    command = [arg for arg in command if not arg.startswith(('--prefix=', '--enable-lto'))]
    command += ['--prefix=' + str(work / 'install'), '--enable-lto=1']
    report = {'schema': 'yblod.qsv-bl-isolated-build.v1', 'source_only': True,
              'source_sha256': {name: digest(work / name) for name in GUARDS},
              'patch_sha256': {p.name: digest(p) for p in patches},
              'build_completed': False, 'sdk_sources_unchanged': True,
              'runtime_qualified': False}
    if args.build or args.configure:
        toolchain = args.sdk.resolve() / 'build.LibreELEC-Generic.x86_64-13.0-devel/toolchain/bin'
        sysroot = toolchain.parent / 'x86_64-libreelec-linux-gnu/sysroot'
        env = dict(os.environ, CCACHE_DISABLE='1',
                   PATH=str(toolchain) + ':' + str(toolchain.parent / 'sbin') + ':' + os.environ['PATH'],
                   PKG_CONFIG=str(toolchain / 'pkg-config'), PKG_CONFIG_PATH='',
                   PKG_CONFIG_LIBDIR=str(sysroot / 'usr/lib/pkgconfig') + ':' +
                                     str(sysroot / 'usr/share/pkgconfig'),
                   PKG_CONFIG_SYSROOT_BASE=str(toolchain.parent.parent),
                   PKG_CONFIG_SYSROOT_DIR=str(sysroot),
                   PKG_CONFIG_ALLOW_SYSTEM_CFLAGS='1', PKG_CONFIG_ALLOW_SYSTEM_LIBS='1')
        run_owned([str(work / 'configure')] + command, work, 600, env)
        config = (work / 'config_components.h').read_text() + (work / 'config.h').read_text()
        for macro in ('CONFIG_HEVC_QSV_DECODER', 'CONFIG_DOVI_RPUDEC', 'CONFIG_HEVCPARSE'):
            assert re.search(r'^#define ' + macro + r' 1$', config, re.M), macro
        baseline_config = (source / 'config_components.h').read_text() + (source / 'config.h').read_text()
        enabled = re.findall(r'^#define (CONFIG_\w+) 1$', baseline_config, re.M)
        for macro in enabled:
            assert re.search(r'^#define ' + macro + r' 1$', config, re.M), macro
        report['configuration_completed'] = True
        report['all_original_enabled_configuration_macros_preserved'] = True
        for key in ('CFLAGS', 'LDFLAGS'):
            line = next(line.split('=', 1)[1] for line in
                        (work / 'ffbuild/config.mak').read_text().splitlines()
                        if line.startswith(key + '='))
            assert [arg for arg in shlex.split(line) if arg.startswith('-flto')][-1] == '-flto=1'
    if args.build:
        process = None
        try:
            process = subprocess.Popen(['make', '-j1'], cwd=work, env=env, start_new_session=True)
            deadline = time.monotonic() + 14400
            while process.poll() is None:
                workers = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
                assert sum(bool(re.fullmatch(r'lto1(?:-ltrans)?', x.strip())) for x in workers) <= 1
                assert time.monotonic() < deadline, 'Four-hour private build timeout'
                time.sleep(1)
            assert process.returncode == 0
        finally:
            terminate(process)
        libraries = {}
        for path in sorted(work.glob('lib*/lib*.so.*')):
            if path.is_file() and not path.is_symlink():
                libraries[str(path.relative_to(work))] = {'sha256': digest(path),
                                                        'bytes': path.stat().st_size}
        assert libraries and any(name.startswith('libavcodec/') for name in libraries)
        report.update(build_completed=True, libraries=libraries)
    assert before == {name: digest(source / name) for name in GUARDS}
    report['resources'] = resources()
    output = work.parent / 'isolated-ffmpeg-build-results.json'
    with output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'prepared': True, 'build_completed': report['build_completed'],
                      'sdk_sources_unchanged': True, 'runtime_qualified': False}))

if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError('Private build interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        main()
    except BaseException as error:
        cg = pathlib.Path('/sys/fs/cgroup')
        failure = {'schema': 'yblod.qsv-bl-isolated-build-failure.v1',
                   'build_completed': False, 'error_type': type(error).__name__,
                   'runtime_qualified': False,
                   'resources': {name: (cg / name).read_text().strip() for name in
                                 ('memory.peak', 'memory.events', 'memory.swap.current',
                                  'memory.swap.peak')}}
        with pathlib.Path('/lab/isolated-ffmpeg-failure.json').open('x') as stream:
            json.dump(failure, stream, indent=2)
            stream.write('\n')
        raise
