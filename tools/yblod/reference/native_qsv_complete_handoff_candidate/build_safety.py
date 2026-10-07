#!/usr/bin/env python3
"""Plan by default; independently prepare or build a copied Kodi candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import time

BUILD = 'build.LibreELEC-Generic.x86_64-13.0-devel'
KODI = BUILD + '/build/kodi-22.0rc1-Piers'
OBJ = '.x86_64-libreelec-linux-gnu'
SYSROOT = BUILD + '/toolchain/x86_64-libreelec-linux-gnu/sysroot'
IMAGE = 'sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e'
CONTROL = Path(__file__).resolve().parent
COMPILER_TMP_LIMIT = 2147483648


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def dump(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)


def run(args, **kwargs):
    kwargs.setdefault('timeout', 30)
    return subprocess.run(list(map(str, args)), check=True, text=True, **kwargs)


def available_memory():
    return next(int(s.split()[1]) * 1024 for s in Path('/proc/meminfo').read_text().splitlines()
                if s.startswith('MemAvailable:'))


def compiler_tmp_usage(output):
    directory = output / 'compiler-tmp'
    assert not directory.is_symlink() and directory.is_dir(), 'Private compiler TMPDIR required'
    assert directory.resolve() == output.resolve() / 'compiler-tmp', 'Compiler TMPDIR escaped output'
    assert directory.stat().st_dev == output.stat().st_dev, 'Compiler TMPDIR must use output filesystem'
    size = 0
    for current, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            try:
                item = path.lstat()
            except FileNotFoundError:
                continue
            assert not stat.S_ISLNK(item.st_mode), 'Unexpected compiler TMPDIR symlink'
            if stat.S_ISREG(item.st_mode):
                size += item.st_size
    assert size <= COMPILER_TMP_LIMIT, 'Compiler TMPDIR sampled budget exceeded'
    assert shutil.disk_usage(directory).free >= 2147483648, 'Compiler TMPDIR disk reserve'
    return size


def host_reserves(directory, budgets):
    result = {'free_disk_bytes': shutil.disk_usage(directory).free,
              'host_available_memory_bytes': available_memory()}
    assert result['free_disk_bytes'] >= budgets['minimum_free_disk_bytes'], 'Disk preflight'
    assert result['host_available_memory_bytes'] >= budgets['minimum_host_available_memory_bytes'], 'Host memory preflight'
    return result


def inspect_owned(cid):
    assert re.fullmatch('[0-9a-f]{64}', cid)
    value = json.loads(run(['docker', 'inspect', cid], capture_output=True, timeout=15).stdout)[0]
    assert value['Id'] == cid and value['Image'] == IMAGE, 'Container ownership mismatch'
    return value


def validate_container(description, mounts):
    config = description['HostConfig']
    assert config['Memory'] == 4294967296 and config['MemorySwap'] == 4294967296
    assert config['NanoCpus'] == 4000000000 and config['NetworkMode'] == 'none'
    assert config['ReadonlyRootfs'] and not config.get('Privileged')
    assert not config.get('Devices') and not config.get('DeviceRequests')
    actual = {m['Destination']: (m['Source'], m['RW']) for m in description['Mounts'] if m['Type'] == 'bind'}
    assert actual == {d: (str(s), w) for s, d, w in mounts}


def sample_resources(cid):
    result = {'exact_owned_cid': cid, 'sampled': False, 'final': False}
    try:
        if inspect_owned(cid)['State']['Running']:
            values = {}
            for name in ('memory.peak', 'memory.events', 'memory.swap.current', 'memory.swap.peak'):
                values[name] = run(['docker', 'exec', cid, 'cat', '/sys/fs/cgroup/' + name],
                                   capture_output=True, timeout=5).stdout.strip()
            result.update(sampled=True, resources=values)
    except (subprocess.SubprocessError, AssertionError, OSError) as error:
        result['sample_error_type'] = type(error).__name__
    return result


def cleanup_owned(cid, process=None):
    """Only the exact ID returned by our docker create is eligible for cleanup."""
    assert re.fullmatch('[0-9a-f]{64}', cid)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)
    try:
        running = inspect_owned(cid)['State']['Running']
    except (subprocess.SubprocessError, OSError):
        running = True
    if running:
        try:
            run(['docker', 'stop', '--time', '10', cid], timeout=25)
        except (subprocess.SubprocessError, OSError):
            run(['docker', 'kill', cid], timeout=15)
        run(['docker', 'wait', cid], capture_output=True, timeout=20)
    if process is not None:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    final = inspect_owned(cid)
    assert not final['State']['Running'] and not final['State'].get('Restarting'), 'Owned container not terminal'
    assert final['State'].get('Status') in ('exited', 'created', 'dead'), 'Unconfirmed terminal state'
    return final


def inventory(root):
    files, links = {}, {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                links[relative] = os.readlink(path)
            elif path.is_file():
                files[relative] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    return {'files': files, 'links': links}


def verify_tree(root, expected, source_only=False):
    for name, value in expected['files'].items():
        if source_only and name.split('/')[0].startswith('.x86_64-'):
            continue
        assert (root / name).stat().st_size == value['bytes']
        assert digest(root / name) == value['sha256'], name
    for name, target in expected['links'].items():
        if source_only and name.split('/')[0].startswith('.x86_64-'):
            continue
        assert os.readlink(root / name) == target, name


def original_file(sdk, container_path):
    """Resolve SDK symlinks using their actual /build container namespace."""
    current = str(container_path)
    for unused in range(32):
        assert current.startswith('/build/')
        path = sdk / current[len('/build/'):]
        if not path.is_symlink():
            assert path.is_file()
            return path, current
        target = os.readlink(path)
        current = os.path.normpath(target if target.startswith('/') else str(Path(current).parent / target))
    raise RuntimeError('SDK symlink loop')


def host():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('plan', 'prepare', 'build'), default='plan')
    for name in ('sdk', 'public', 'candidate', 'closure-manifest', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    sdk, public, candidate = (p.resolve(strict=True) for p in (args.sdk, args.public, args.candidate))
    output = args.output.absolute()
    assert output.parent.resolve(strict=True) == public / 'target'
    assert re.fullmatch(r'qsv-bl-el-kodi-[a-z0-9-]+', output.name)
    assert not output.is_symlink()
    manifest = json.loads((CONTROL / 'source-manifest.json').read_text())
    budgets = manifest['budgets']
    host_reserves(output.parent, budgets)
    kodi = sdk / KODI
    for name, sha in manifest['source_sha256'].items():
        assert digest(kodi / name) == sha, name
    assert digest(kodi / OBJ / 'kodi.bin') == manifest['sdk_kodi_binary_sha256']
    reference = public / 'tools/yblod/reference/native_qsv_bl_kodi_integration_candidate'
    patches = [(CONTROL if 'async-depth' in name else reference) / name
               for name in manifest['patch_sha256']]
    for patch in patches:
        assert digest(patch) == manifest['patch_sha256'][patch.name]
    report_path = public / 'tools/yblod/reference/native_qsv_bl_compatible_param_candidate/COMPATIBLE_PARAM_BUILD_RESULTS.json'
    assert digest(report_path) == manifest['compatible_build_report_sha256']
    report = json.loads(report_path.read_text())
    assert report['build_completed'] and not report['diagnostic_only']
    for category in ('configuration_sha256', 'native_source_and_abi_sha256'):
        for name, sha in report[category].items():
            assert digest(candidate / 'ffmpeg-bl-qsv-candidate' / name) == sha
    assert digest(candidate / 'ffmpeg-bl-qsv-candidate/libavcodec/qsvdec.c') == report['qsvdec_sha256']
    library_mounts = []
    for name, item in report['libraries'].items():
        source = candidate / 'ffmpeg-bl-qsv-candidate' / name
        assert digest(source) == item['sha256'] and source.stat().st_size == item['bytes']
        unused, destination = original_file(sdk, '/build/' + SYSROOT + '/usr/lib/' + Path(name).name)
        library_mounts.append((source.resolve(strict=True), destination, False))
    host_reserves(output.parent, budgets)
    before = inventory(kodi)
    size = sum(v['bytes'] for v in before['files'].values())
    plan = {'copy_bytes': size, 'copy_files': len(before['files']), 'copy_symlinks': len(before['links']),
            'free_disk_bytes': shutil.disk_usage(output.parent).free,
            'host_available_memory_bytes': available_memory(), 'budgets': budgets,
            'baseline_binary_sha256': manifest['sdk_kodi_binary_sha256'],
            'library_overrides': [{'source': str(s), 'destination': d} for s, d, unused in library_mounts],
            'build_started': False, 'deployment_supported': False}
    assert size <= budgets['maximum_copy_bytes'] and len(before['files']) <= budgets['maximum_copy_files']
    assert plan['free_disk_bytes'] >= budgets['minimum_free_disk_bytes']
    assert plan['host_available_memory_bytes'] >= budgets['minimum_host_available_memory_bytes']
    print(json.dumps(plan, indent=2), flush=True)
    if args.phase == 'plan':
        return
    if args.phase == 'prepare':
        host_reserves(output.parent, budgets)
        output.mkdir(exist_ok=False)
        (output / 'compiler-tmp').mkdir(mode=0o700)
        dump(output / 'before-copy-plan.json', plan)
        dump(output / 'baseline-tree.json', before)
        shutil.copytree(kodi, output / 'kodi', symlinks=True, copy_function=shutil.copy2)
        verify_tree(output / 'kodi', before)
        verify_tree(kodi, before)
        for name in before['files']:
            original, copied = (kodi / name).stat(), (output / 'kodi' / name).stat()
            assert (original.st_dev, original.st_ino) != (copied.st_dev, copied.st_ino)
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', patch], cwd=output / 'kodi')
        decoder = output / 'kodi/xbmc/cores/VideoPlayer/DVDCodecs/Video/DVDVideoCodecFFmpeg.cpp'
        assert digest(decoder) == manifest['prepared_decoder_sha256']
        assert digest(output / 'kodi/tools/dvbridge/dvbridge_fel.c') == manifest['source_sha256']['tools/dvbridge/dvbridge_fel.c']
        dump(output / 'prepared-tree.json', inventory(output / 'kodi'))
        dump(output / 'preparation.json', {'input_manifest_sha256': digest(CONTROL / 'source-manifest.json'),
                                         'controller_sha256': digest(__file__), 'phase': 'prepared',
                                         'copy_hardlinks': False, 'build_started': False})
        return
    preparation = json.loads((output / 'preparation.json').read_text())
    assert preparation['input_manifest_sha256'] == digest(CONTROL / 'source-manifest.json')
    assert preparation['controller_sha256'] == digest(__file__)
    verify_tree(output / 'kodi', json.loads((output / 'prepared-tree.json').read_text()))
    assert not (output / 'container-before.json').exists(), 'Fresh build attempt required'
    assert compiler_tmp_usage(output) == 0, 'Fresh empty compiler TMPDIR required'
    mounts = [(sdk, '/build', False), (output / 'kodi', '/build/' + KODI, True),
              (candidate, '/candidate', False), (CONTROL, '/control', False),
              (report_path, '/compatible.json', False),
              (args.closure_manifest.absolute(), '/closure.json', False), (output, '/lab', True)] + library_mounts
    command = ['docker', 'create', '--memory=4g', '--memory-swap=4g', '--cpus=1', '--network=none',
               '--read-only', '--tmpfs', '/tmp:rw,nosuid,exec,size=128m', '--user', '0:0',
               '-e', 'CCACHE_DISABLE=1', '-e', 'PYTHONDONTWRITEBYTECODE=1',
               '-e', 'TMPDIR=/lab/compiler-tmp']
    for source, destination, writable in mounts:
        assert ',' not in str(source)
        command += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination + ('' if writable else ',readonly')]
    command += ['--entrypoint', '/usr/bin/python3', IMAGE, '/control/prepare_build_qsv_kodi.py', '--inside']
    host_reserves(output.parent, budgets)
    command[2:2] = ['--cidfile', str(output / 'owned.cid')]
    try:
        cid = run(command, capture_output=True, timeout=60).stdout.strip()
    except (subprocess.SubprocessError, OSError) as error:
        recovered = (output / 'owned.cid').read_text().strip() if (output / 'owned.cid').is_file() else ''
        confirmed = False
        if re.fullmatch('[0-9a-f]{64}', recovered):
            cleanup_owned(recovered)
            confirmed = True
        dump(output / 'create-failure.json', {'create_error_type': type(error).__name__,
             'exact_owned_cid': recovered or None, 'terminal_confirmed': confirmed,
             'full_build_completed': False})
        raise
    assert re.fullmatch('[0-9a-f]{64}', cid)
    process = None
    completed = False
    maximum_tmp_bytes = 0
    def stop_signal(unused_signum, unused_frame):
        raise RuntimeError('Owned build interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop_signal)
    try:
        description = inspect_owned(cid)
        validate_container(description, mounts)
        dump(output / 'container-before.json', description)
        with (output / 'build.log').open('x') as log, (output / 'resource-samples.jsonl').open('x') as samples:
            process = subprocess.Popen(['docker', 'start', '-a', cid], stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + budgets['build_timeout_seconds']
            next_sample = time.monotonic()
            while process.poll() is None:
                assert time.monotonic() < deadline, 'Build deadline'
                assert available_memory() >= budgets['abort_host_available_memory_below_bytes'], 'Host memory pressure'
                assert shutil.disk_usage(output).free >= 2147483648, 'Disk reserve'
                maximum_tmp_bytes = max(maximum_tmp_bytes, compiler_tmp_usage(output))
                if time.monotonic() >= next_sample:
                    samples.write(json.dumps(sample_resources(cid)) + '\n')
                    samples.flush()
                    next_sample = time.monotonic() + 15
                time.sleep(2)
            assert process.returncode == 0
        final = inspect_owned(cid)
        assert not final['State']['Running'] and final['State']['ExitCode'] == 0 and not final['State']['OOMKilled']
        verify_tree(kodi, before)
        completed = True
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        sample = sample_resources(cid)
        dump(output / 'resources-before-cleanup.json', sample)
        try:
            final = cleanup_owned(cid, process)
            dump(output / 'container-after.json', final)
            dump(output / 'controller-result.json', {'exact_owned_cid': cid,
                 'full_build_completed': completed, 'terminal_confirmed': True,
                 'exit_code': final['State']['ExitCode'], 'oom_killed': final['State']['OOMKilled'],
                 'final_resource_report_present': (output / 'container-resource-final.json').is_file(),
                 'compiler_tmp_max_sampled_bytes': maximum_tmp_bytes,
                 'compiler_tmp_sampled_limit_bytes': COMPILER_TMP_LIMIT,
                 'runtime_or_pixels_qualified': False})
        except BaseException as error:
            dump(output / 'controller-cleanup-failure.json', {'exact_owned_cid': cid,
                 'full_build_completed': False, 'terminal_confirmed': False,
                 'cleanup_error_type': type(error).__name__, 'sampled_resources': sample})
            raise
        finally:
            print('owned_container=' + cid, flush=True)


def inside():
    manifest = json.loads((CONTROL / 'source-manifest.json').read_text())
    cg = Path('/sys/fs/cgroup')
    assert (cg / 'memory.max').read_text().strip() == '4294967296'
    assert (cg / 'memory.swap.max').read_text().strip() == '0'
    quota, period = map(int, (cg / 'cpu.max').read_text().split())
    assert 0 < quota <= period and not Path('/dev/dri').exists()
    assert os.environ.get('TMPDIR') == '/lab/compiler-tmp'
    assert compiler_tmp_usage(Path('/lab')) == 0
    assert Path('/lab/compiler-tmp').stat().st_dev != Path('/tmp').stat().st_dev
    assert digest('/compatible.json') == manifest['compatible_build_report_sha256']
    assert digest('/closure.json') == manifest['qualified_closure_report_sha256']
    closure = json.loads(Path('/closure.json').read_text())['files']
    assert len(closure) == 27
    for path, item in closure.items():
        assert path == item['path'] and (path.startswith('/build/') or path.startswith('/candidate/ffmpeg-bl-qsv-candidate/'))
        assert digest(path) == item['sha256'], path
    report = json.loads(Path('/compatible.json').read_text())
    for name, item in report['libraries'].items():
        assert digest(Path('/build') / SYSROOT / 'usr/lib' / Path(name).name) == item['sha256']
    kodi = Path('/build') / KODI
    build = kodi / OBJ
    prepared = json.loads(Path('/lab/prepared-tree.json').read_text())
    verify_tree(kodi, prepared)
    toolchain = Path('/build') / BUILD / 'toolchain'
    sysroot = Path('/build') / SYSROOT
    os.environ.update(PATH=str(toolchain / 'bin') + ':' + os.environ['PATH'],
                      PKG_CONFIG_PATH='', PKG_CONFIG_LIBDIR=str(sysroot / 'usr/lib/pkgconfig') + ':' + str(sysroot / 'usr/share/pkgconfig'),
                      PKG_CONFIG_SYSROOT_DIR=str(sysroot), CCACHE_DISABLE='1')
    ninja = toolchain / 'bin/ninja'
    run([ninja, '-j1', 'build.ninja'], cwd=build, timeout=180)
    rules = build / 'CMakeFiles/rules.ninja'
    text = rules.read_text()
    start = text.index('rule CXX_EXECUTABLE_LINKER__kodi_Release\n')
    end = text.index('\n\n', start)
    block = text[start:end]
    assert block.count('$LINK_LIBRARIES') == 1
    block = block.replace('$LINK_LIBRARIES', '$LINK_LIBRARIES -flto=1')
    rules.write_text(text[:start] + block + text[end:])
    commands = run([ninja, '-t', 'commands', 'kodi.bin'], cwd=build, capture_output=True).stdout
    final = [s for s in commands.splitlines() if ' -o kodi.bin ' in s]
    assert len(final) == 1 and re.findall(r'(?<!\S)-flto(?:=\S+)?', final[0])[-1] == '-flto=1'
    assert 'QsvMappedBuffer.cpp' in commands
    Path('/lab/final-build-commands.txt').write_text(commands)
    process = subprocess.Popen([str(ninja), '-j1', 'kodi'], cwd=build, start_new_session=True)
    maximum_workers = 0
    try:
        deadline = time.monotonic() + 5100
        while process.poll() is None:
            workers = sum(bool(re.fullmatch(r'lto1(?:-ltrans)?', s.strip()))
                          for s in run(['ps', '-eo', 'comm='], capture_output=True).stdout.splitlines())
            maximum_workers = max(maximum_workers, workers)
            assert workers <= 1 and time.monotonic() < deadline
            time.sleep(2)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
    verify_tree(kodi, prepared, source_only=True)
    for name, item in report['libraries'].items():
        assert digest(Path('/build') / SYSROOT / 'usr/lib' / Path(name).name) == item['sha256']
    loader = sysroot / 'usr/lib/ld-linux-x86-64.so.2'
    listed = run([loader, '--library-path', str(sysroot / 'usr/lib') + ':' + str(toolchain / 'x86_64-libreelec-linux-gnu/lib'),
                  '--list', build / 'kodi.bin'], capture_output=True).stdout
    assert 'not found' not in listed
    loaded = {}
    for line in listed.splitlines():
        match = re.match(r'\s*(\S+) => (/\S+) \(', line)
        if match:
            soname, path = match.groups()
            assert path.startswith('/build/'), path
            loaded[soname] = {'path': path, 'sha256': digest(path)}
    for name, item in report['libraries'].items():
        soname = Path(name).name
        if soname in loaded:
            assert loaded[soname]['sha256'] == item['sha256']
    assert loaded['libavcodec.so.63']['sha256'] == manifest['qualified_libavcodec_sha256']
    resources = {n: (cg / n).read_text().strip() for n in ('memory.peak', 'memory.events', 'memory.swap.current', 'memory.swap.peak')}
    assert all(int(s.split()[1]) == 0 for s in resources['memory.events'].splitlines())
    assert resources['memory.swap.current'] == resources['memory.swap.peak'] == '0'
    dump('/lab/build-results.json', {'full_kodi_link_completed': True, 'runtime_or_pixels_qualified': False,
         'binary_sha256': digest(build / 'kodi.bin'), 'binary_bytes': (build / 'kodi.bin').stat().st_size,
         'qualified_probe_closure_sha256': manifest['qualified_closure_report_sha256'],
         'qualified_probe_closure_files': 27, 'kodi_loader_list': loaded,
         'option_async_depth_requested': 1, 'sdk_effective_async_depth_observed': False,
         'maximum_lto_workers_observed': maximum_workers, 'resources': resources})


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--inside']:
        completed = False
        try:
            inside()
            completed = True
        finally:
            cg = Path('/sys/fs/cgroup')
            dump('/lab/container-resource-final.json', {
                'full_build_completed': completed, 'final': True,
                'resources': {n: (cg / n).read_text().strip() for n in
                ('memory.peak', 'memory.events', 'memory.swap.current', 'memory.swap.peak')}})
    else:
        host()
