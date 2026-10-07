#!/usr/bin/env python3
"""Review-gated fresh keyflag library copy; never changes qualified c0eee."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import build_safety as s

CONTROL = Path(__file__).resolve().parent
REPORT_SHA = 'd46b736f6288ada414b1384bdf7cba43094b5e7fe7dae4b0f008ad7c99a14cae'
OLD = {'qsv_dovi.h': 'c7a409ec09971a745fbba8b5d87e14e770d501e8ef8f57a232029415f8254293',
       'qsvdec.c': 'ffe1541b756e835ca2384d50192f3a244c59e68a5bd24e39de4ee5dcd9e9378d',
       'hevc/parser.c': '0876fd1038b5e91130b9f15fe834e4d3db212ee4985fcd35b6b227faaba1dc3d'}
NEW = {'qsv_dovi.h': '5ebee6df9f36cfd4cd1395200371f0da10ec3654ed8e3cb50bd433428c009969',
       'qsvdec.c': '18b31d4820526b103c4a76b538335fae33955342cf267676af7a4b2e8cc80e59',
       'hevc/parser.c': '6d88b5156318af34c3b4485848a2c4c5ce05978c513cc07fce3a3aecc0f8d572'}
BUDGETS = {'minimum_free_disk_bytes': 6442450944, 'minimum_host_available_memory_bytes': 6442450944}


def guards(root, report, changed=False, built=False):
    for group in ('configuration_sha256', 'native_source_and_abi_sha256'):
        for name, wanted in report[group].items():
            expected = NEW.get(name.removeprefix('libavcodec/'), wanted) if changed else wanted
            assert s.digest(root / name) == expected, name
    for name, wanted in (NEW if changed else OLD).items():
        assert s.digest(root / 'libavcodec' / name) == wanted, name
    for name, item in report['libraries'].items():
        if built and name.startswith('libavcodec/'):
            continue
        assert s.digest(root / name) == item['sha256'], name
        assert (root / name).stat().st_size == item['bytes'], name


def result_identity(report):
    # Whitelist preserved contracts; never inherit the base patch/source claims.
    native_pins = dict(report['native_source_and_abi_sha256'])
    native_pins['libavcodec/hevc/parser.c'] = NEW['hevc/parser.c']
    result = {'schema': 'yblod.qsv-frame-properties-library-build.v1',
              'base_report_sha256': REPORT_SHA,
              'base_provenance': {'schema': report['schema'],
                                  'compatible_param_patch_sha256': report['compatible_param_patch_sha256'],
                                  'qsvdec_sha256': report['qsvdec_sha256']},
              'qsvdec_sha256': NEW['qsvdec.c'], 'qsv_dovi_header_sha256': NEW['qsv_dovi.h'],
              'source_sha256': dict(NEW),
              'configuration_sha256': report['configuration_sha256'],
              'native_source_and_abi_sha256': native_pins,
              'diagnostic_only': False, 'public_abi_guards_unchanged': True,
              'hevc_parser_vui_export_added': True, 'worker_limit': 4}
    validate_result_identity(result)
    return result


def validate_result_identity(result):
    assert result['source_sha256'] == NEW
    assert result['qsvdec_sha256'] == NEW['qsvdec.c']
    assert result['qsv_dovi_header_sha256'] == NEW['qsv_dovi.h']
    assert 'compatible_param_patch_sha256' not in result


def inside():
    cg = Path('/sys/fs/cgroup')
    assert (cg / 'memory.max').read_text().strip() == '4294967296'
    assert (cg / 'memory.swap.max').read_text().strip() == '0'
    assert not Path('/dev/dri').exists()
    output, original = Path('/lab'), Path('/original')
    work = output / 'ffmpeg-bl-qsv-candidate'
    assert s.digest('/report.json') == REPORT_SHA
    report = json.loads(Path('/report.json').read_text())
    completed = False
    process = None
    max_workers = 0
    try:
        guards(original, report)
        tree = s.inventory(original)
        s.dump(output / 'baseline-tree.json', tree)
        assert not work.exists()
        shutil.copytree(original, work, symlinks=True, copy_function=shutil.copy2)
        assert s.inventory(work) == tree
        for name in tree['files']:
            assert (original / name).stat().st_ino != (work / name).stat().st_ino or (original / name).stat().st_dev != (work / name).stat().st_dev
        for name, wanted in NEW.items():
            source = Path('/sources') / name
            assert s.digest(source) == wanted
            shutil.copy2(source, work / 'libavcodec' / name)
            # Ensure inherited object timestamps cannot suppress recompilation.
            os.utime(work / 'libavcodec' / name, None)
        prepared = s.inventory(work)
        assert prepared['links'] == tree['links']
        assert set(prepared['files']) == set(tree['files'])
        assert {n for n in tree['files'] if tree['files'][n] != prepared['files'][n]} == {'libavcodec/' + n for n in NEW}
        s.dump(output / 'prepared-tree.json', prepared)
        guards(work, report, changed=True)
        config = (work / 'ffbuild/config.mak').read_text()
        assert '/lab/ffmpeg-bl-qsv-candidate' in config
        for variable in ('CFLAGS', 'LDFLAGS'):
            row = next(x for x in config.splitlines() if x.startswith(variable + '='))
            assert re.findall(r'-flto(?:=\S+)?', row)[-1] == '-flto=1'
        toolchain = Path('/build') / s.BUILD / 'toolchain'
        sysroot = Path('/build') / s.SYSROOT
        env = dict(os.environ, CCACHE_DISABLE='1', TMPDIR='/lab/compiler-tmp',
                   PATH=str(toolchain / 'bin') + ':' + str(toolchain / 'sbin') + ':' + os.environ['PATH'],
                   PKG_CONFIG=str(toolchain / 'bin/pkg-config'), PKG_CONFIG_PATH='',
                   PKG_CONFIG_LIBDIR=str(sysroot / 'usr/lib/pkgconfig') + ':' + str(sysroot / 'usr/share/pkgconfig'),
                   PKG_CONFIG_SYSROOT_BASE=str(toolchain.parent), PKG_CONFIG_SYSROOT_DIR=str(sysroot),
                   PKG_CONFIG_ALLOW_SYSTEM_CFLAGS='1', PKG_CONFIG_ALLOW_SYSTEM_LIBS='1')
        overrides = []
        for variable in ('CFLAGS', 'LDFLAGS'):
            row = next(x for x in config.splitlines() if x.startswith(variable + '='))
            overrides.append(re.sub(r'-flto=1(?=\s|$)', '-flto=4', row))
        process = subprocess.Popen(['make', '-j4', *overrides, 'libavcodec/libavcodec.so.63'], cwd=work, env=env, start_new_session=True)
        deadline = time.monotonic() + 3600
        while process.poll() is None:
            names = s.run(['ps', '-eo', 'comm='], capture_output=True, timeout=10).stdout.splitlines()
            workers = sum(bool(re.fullmatch(r'lto1(?:-ltrans)?', n.strip())) for n in names)
            max_workers = max(max_workers, workers)
            assert workers <= 4 and time.monotonic() < deadline
            time.sleep(1)
        assert process.returncode == 0
        guards(work, report, changed=True, built=True)
        assert s.inventory(original) == tree
        # Every public header and native source stays byte-identical; only the
        # private QSV metadata header and qsvdec implementation are allowed edits.
        for name, item in prepared['files'].items():
            if name.endswith(('.c', '.h')):
                assert s.digest(work / name) == item['sha256'], name
        readelf = toolchain / 'bin/x86_64-libreelec-linux-gnu-readelf'
        oldlib, newlib = original / 'libavcodec/libavcodec.so.63', work / 'libavcodec/libavcodec.so.63'
        def elf_contract(lib):
            dynamic = s.run([readelf, '-d', lib], capture_output=True).stdout
            symbols = s.run([readelf, '--dyn-syms', '--wide', lib], capture_output=True).stdout
            return {'needed_soname': [x.strip() for x in dynamic.splitlines() if '(NEEDED)' in x or '(SONAME)' in x],
                    'exports': sorted(' '.join(x.split()[3:]) for x in symbols.splitlines()
                                      if len(x.split()) >= 8 and x.split()[4] in ('GLOBAL', 'WEAK') and x.split()[6] != 'UND')}
        oldabi, newabi = elf_contract(oldlib), elf_contract(newlib)
        assert oldabi == newabi, 'Export/SONAME/dependency change requires review'
        result = result_identity(report)
        result.update(schema='yblod.qsv-frame-properties-library-build.v1', build_completed=True,
                      hardware_or_quality_qualified=False, source_sha256=NEW,
                      original_candidate_unchanged=True, public_headers_unchanged=True,
                      elf_contract_unchanged=True, ltrans_workers_max_observed=max_workers)
        result['libraries'] = dict(report['libraries'])
        result['libraries']['libavcodec/libavcodec.so.63'] = {'sha256': s.digest(newlib), 'bytes': newlib.stat().st_size}
        validate_result_identity(result)
        s.dump(output / 'elf-contract.json', newabi)
        s.dump(output / 'keyflag-build-results.json', result)
        completed = True
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        s.dump(output / 'container-resource-final.json', {'build_completed': completed,
               'resources': {n: (cg / n).read_text().strip() for n in
                             ('memory.peak', 'memory.events', 'memory.swap.current', 'memory.swap.peak')}})


def host():
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=('plan', 'build'), default='plan')
    for name in ('sdk', 'public', 'sources', 'output'):
        p.add_argument('--' + name, required=True, type=Path)
    a = p.parse_args()
    sdk, public, sources = a.sdk.resolve(), a.public.resolve(), a.sources.resolve()
    output = a.output.absolute()
    assert output.parent.resolve() == public / 'target'
    assert re.fullmatch('qsv-bl-keyflag-library-[a-z0-9-]+', output.name)
    assert not output.exists() and not output.is_symlink()
    assert s.digest(CONTROL / 'build_safety.py') == '19170cc3a04f7570618e49459f01635af3d4bc0ad30162360903fbb105742856'
    reserve = s.host_reserves(output.parent, BUDGETS)
    original = public / 'target/qsv-bl-compatible-param-library-20261006/ffmpeg-bl-qsv-candidate'
    report_path = public / 'tools/yblod/reference/native_qsv_bl_compatible_param_candidate/COMPATIBLE_PARAM_BUILD_RESULTS.json'
    assert s.digest(report_path) == REPORT_SHA
    guards(original, json.loads(report_path.read_text()))
    for name, wanted in NEW.items():
        assert s.digest(sources / name) == wanted
    tree = s.inventory(original)
    count = len(tree['files'])
    size = sum(x['bytes'] for x in tree['files'].values())
    assert count <= 20000 and size <= 1073741824
    print(json.dumps({'phase': a.phase, 'copy_regular_files': count, 'copy_bytes': size,
                      'limits': '4GiB/noSwap/CPU4/networkNone/noGPU/LTO4', 'reserves': reserve,
                      'source_pins': NEW, 'build_started': False}), flush=True)
    if a.phase == 'plan':
        return
    s.host_reserves(output.parent, BUDGETS)
    output.mkdir()
    (output / 'compiler-tmp').mkdir(mode=0o700)
    s.dump(output / 'plan-tree.json', tree)
    mounts = [(sdk, '/build', False), (original, '/original', False), (sources, '/sources', False),
              (report_path, '/report.json', False), (CONTROL, '/control', False), (output, '/lab', True)]
    command = ['docker', 'create', '--cidfile', str(output / 'owned.cid'), '--memory=4g', '--memory-swap=4g',
               '--cpus=4', '--network=none', '--read-only', '--tmpfs', '/tmp:rw,nosuid,exec,size=64m',
               '--user', '0:0', '-e', 'CCACHE_DISABLE=1', '-e', 'PYTHONDONTWRITEBYTECODE=1']
    for source, destination, writable in mounts:
        assert ',' not in str(source)
        command += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination + ('' if writable else ',readonly')]
    command += ['--entrypoint', '/usr/bin/python3', s.IMAGE, '/control/build_keyflag.py', '--inside']
    try:
        cid = s.run(command, capture_output=True, timeout=60).stdout.strip()
    except BaseException:
        if (output / 'owned.cid').is_file():
            cid = (output / 'owned.cid').read_text().strip()
            s.dump(output / 'create-failure-terminal.json', s.cleanup_owned(cid))
        raise
    process = None
    completed = False
    def interrupted(*unused):
        raise RuntimeError('Owned keyflag build interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        before = s.inspect_owned(cid)
        s.validate_container(before, mounts)
        s.dump(output / 'container-before.json', before)
        print('owned_container=' + cid, flush=True)
        with (output / 'build.log').open('x') as log, (output / 'resource-samples.jsonl').open('x') as samples:
            process = subprocess.Popen(['docker', 'start', '-a', cid], stdout=log, stderr=subprocess.STDOUT)
            deadline, next_sample = time.monotonic() + 3900, time.monotonic()
            while process.poll() is None:
                assert time.monotonic() < deadline
                assert s.available_memory() >= 2147483648
                s.compiler_tmp_usage(output)
                if time.monotonic() >= next_sample:
                    samples.write(json.dumps(s.sample_resources(cid)) + '\n')
                    samples.flush()
                    next_sample = time.monotonic() + 15
                time.sleep(2)
            assert process.returncode == 0
        after = s.inspect_owned(cid)
        assert after['State']['ExitCode'] == 0 and not after['State']['OOMKilled']
        assert s.inventory(original) == tree
        final_resources = json.loads((output / 'container-resource-final.json').read_text())['resources']
        assert all(int(x.split()[1]) == 0 for x in final_resources['memory.events'].splitlines())
        assert int(final_resources['memory.swap.current']) == int(final_resources['memory.swap.peak']) == 0
        completed = True
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        s.dump(output / 'resources-before-cleanup.json', s.sample_resources(cid))
        try:
            after = s.cleanup_owned(cid, process)
            s.dump(output / 'container-after.json', after)
            s.dump(output / 'controller-result.json', {'build_completed': completed, 'terminal_confirmed': True,
                   'exact_owned_cid': cid, 'exit_code': after['State']['ExitCode'], 'hardware_or_quality_qualified': False})
        except BaseException as error:
            s.dump(output / 'cleanup-failure.json', {'terminal_confirmed': False, 'error_type': type(error).__name__})
            raise


if __name__ == '__main__':
    if sys.argv[1:] == ['--inside']:
        def stop(*unused):
            raise RuntimeError('Owned build interrupted')
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, stop)
        inside()
    else:
        host()
