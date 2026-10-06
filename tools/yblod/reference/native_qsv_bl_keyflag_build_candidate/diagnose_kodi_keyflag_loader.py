#!/usr/bin/env python3
"""Read ELF headers and ask the target loader to list dependencies; never run Kodi."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/bryan/Projects/libreelec-yblod-reconstruction/target')
CONTROL = ROOT / 'qsv-bl-el-kodi-control-disk-tmp-20261006'
ATTEMPT = ROOT / 'qsv-bl-el-kodi-isolated-disk-tmp-20261006'
OUTPUT = ROOT / 'qsv-bl-el-kodi-loader-keyflag-check-20261006'
KEYFLAG = ROOT / 'qsv-bl-keyflag-library-20261006'
KEYFLAG_REPORT = 'c1024b3856dfe0b9e2d6ddbd9c3de4e273e1c87dfe402f89541fea3a3c1c5c26'
KEYFLAG_CODEC = '871a5b008e907d67bc4ba3b36cc9dbe932657505c194c9d2f34784309c394a95'
BINARY = '0436e639c1f549316cfe960c5bbf7c1eadd2d2a57bdff741ad9295176e47b5c3'
sys.path.insert(0, '/control' if sys.argv[1:] == ['--inside'] else str(CONTROL))
import prepare_build_qsv_kodi as c


def inside():
    cg = Path('/sys/fs/cgroup')
    assert (cg / 'memory.max').read_text().strip() == '1073741824'
    assert (cg / 'memory.swap.max').read_text().strip() == '0'
    assert not Path('/dev/dri').exists()
    binary = Path('/build') / c.KODI / c.OBJ / 'kodi.bin'
    assert c.digest(binary) == BINARY
    tools = Path('/build') / c.BUILD / 'toolchain'
    sysroot = Path('/build') / c.SYSROOT
    manifest = json.loads(Path('/control/source-manifest.json').read_text())
    assert c.digest('/compatible.json') == manifest['compatible_build_report_sha256']
    assert c.digest('/closure.json') == manifest['qualified_closure_report_sha256']
    assert c.digest('/keyflag.json') == KEYFLAG_REPORT
    keyflag = json.loads(Path('/keyflag.json').read_text())
    assert keyflag['base_report_sha256'] == manifest['compatible_build_report_sha256']
    assert keyflag['build_completed'] and keyflag['elf_contract_unchanged']
    assert keyflag['qsvdec_sha256'] == 'a87bbcec949bc5668a0fdcf14100bf20901a9b9242c3df0627aa3ac4dd74e8ed'
    assert keyflag['qsv_dovi_header_sha256'] == 'd0612fbabd19dd9797d17191204d9d57b57789ff00fbab6d638d83f1c8e3350f'
    closure = json.loads(Path('/closure.json').read_text())['files']
    assert len(closure) == 27
    replacements = 0
    for path, item in closure.items():
        assert path == item['path'] and (path.startswith('/build/') or path.startswith('/candidate/ffmpeg-bl-qsv-candidate/'))
        if path == '/candidate/ffmpeg-bl-qsv-candidate/libavcodec/libavcodec.so.63':
            assert item['sha256'] == manifest['qualified_libavcodec_sha256']
            assert c.digest(path) == KEYFLAG_CODEC
            replacements += 1
        else:
            assert c.digest(path) == item['sha256']
    assert replacements == 1
    libraries = keyflag['libraries']
    baseline_libraries = json.loads(Path('/compatible.json').read_text())['libraries']
    assert set(libraries) == set(baseline_libraries)
    for name, item in libraries.items():
        if name == 'libavcodec/libavcodec.so.63':
            assert item['sha256'] == KEYFLAG_CODEC
        else:
            assert item == baseline_libraries[name]
        assert c.digest(sysroot / 'usr/lib' / Path(name).name) == item['sha256']
    assert (sysroot / 'usr/lib/pulseaudio/libpulsecommon-17.0.so').is_file()
    samba = Path('/build') / c.BUILD / 'install_pkg/samba-4.25.0/usr/lib'
    tevent_sha = '9b7934ec9279e49e87f0af5ad69903abef0c64d80d3c95c099f55a1794955442'
    assert c.digest(samba / 'libtevent-private-samba.so') == tevent_sha
    assert c.digest('/retained-kodi.bin') == manifest['sdk_kodi_binary_sha256']
    readelf = c.run([tools / 'bin/x86_64-libreelec-linux-gnu-readelf', '-d', binary], capture_output=True)
    retained = c.run([tools / 'bin/x86_64-libreelec-linux-gnu-readelf', '-d', '/retained-kodi.bin'], capture_output=True)
    needed = [line.strip() for line in readelf.stdout.splitlines() if '(NEEDED)' in line]
    assert needed == [line.strip() for line in retained.stdout.splitlines() if '(NEEDED)' in line]
    (Path('/diag') / 'elf-dynamic.txt').write_text(readelf.stdout)
    command = [str(sysroot / 'usr/lib/ld-linux-x86-64.so.2'), '--library-path',
               str(sysroot / 'usr/lib') + ':' + str(tools / 'x86_64-libreelec-linux-gnu/lib') + ':' +
               str(sysroot / 'usr/lib/pulseaudio') + ':' + str(samba), '--list', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    Path('/diag/loader-stdout.txt').write_text(result.stdout)
    Path('/diag/loader-stderr.txt').write_text(result.stderr)
    loaded = {}
    for line in result.stdout.splitlines():
        match = re.match(r'\s*(\S+) => (/\S+) \(', line)
        if match:
            name, path = match.groups()
            assert path.startswith('/build/'), 'Unexpected host library'
            loaded[name] = {'path': path, 'sha256': c.digest(path)}
    if result.returncode == 0:
        assert loaded['libavcodec.so.63']['sha256'] == KEYFLAG_CODEC
        for name, item in libraries.items():
            soname = Path(name).name
            if soname in loaded:
                assert loaded[soname]['sha256'] == item['sha256']
    assert c.digest(binary) == BINARY
    c.dump('/diag/diagnostic.json', {'binary_sha256': BINARY, 'binary_bytes': binary.stat().st_size,
           'loader_exit_code': result.returncode, 'kodi_executed': False,
           'resolved_libraries': loaded, 'baseline_closure_files_unchanged': 26,
           'explicit_libavcodec_replacements_verified': 1,
           'keyflag_libavcodec_sha256': KEYFLAG_CODEC, 'keyflag_build_report_sha256': KEYFLAG_REPORT,
           'added_sdk_search_subdirectories': ['usr/lib/pulseaudio', 'install_pkg/samba-4.25.0/usr/lib'],
           'retained_binary_sha256': manifest['sdk_kodi_binary_sha256'],
           'retained_and_new_dt_needed_identical': True, 'dt_needed_count': len(needed),
           'samba_tevent_sha256': tevent_sha,
           'samba_tevent_matches_capture_agents_readonly_petunia_observation': True,
           'resources': {n: (cg / n).read_text().strip() for n in
                         ('memory.peak', 'memory.events', 'memory.swap.current', 'memory.swap.peak')}})


def host():
    assert c.digest(CONTROL / 'prepare_build_qsv_kodi.py') == 'fa0272e8d2247c958e7b7e12ec35653fb8e2ff947b4f560e092875b03d15c7d6'
    before = json.loads((ATTEMPT / 'container-before.json').read_text())
    assert before['Id'] == '47f745abf1f1dff9c1afa8233f5ba863a18852416d1c95dbbb7dc8e8d73ba301'
    c.host_reserves(OUTPUT.parent, json.loads((CONTROL / 'source-manifest.json').read_text())['budgets'])
    OUTPUT.mkdir(exist_ok=False)
    mounts = [(Path(m['Source']), m['Destination'], False) for m in before['Mounts'] if m['Type'] == 'bind']
    old_candidate = ROOT / 'qsv-bl-compatible-param-library-20261006'
    replacements = 0
    remapped = []
    for source, destination, writable in mounts:
        if source == old_candidate or old_candidate in source.parents:
            source = KEYFLAG / source.relative_to(old_candidate)
            replacements += 1
        remapped.append((source, destination, writable))
    assert replacements == 9  # candidate root and eight exact sysroot ELF binds
    mounts = remapped + [(KEYFLAG / 'keyflag-build-results.json', '/keyflag.json', False)]
    mounts += [(Path(__file__).resolve().parent, '/diag-control', False), (OUTPUT, '/diag', True)]
    sdk = Path(next(m['Source'] for m in before['Mounts'] if m['Destination'] == '/build'))
    mounts += [(sdk / c.KODI / c.OBJ / 'kodi.bin', '/retained-kodi.bin', False)]
    command = ['docker', 'create', '--memory=1g', '--memory-swap=1g', '--cpus=1', '--network=none',
               '--read-only', '--user', '0:0', '--tmpfs', '/tmp:rw,nosuid,size=32m',
               '-e', 'PYTHONDONTWRITEBYTECODE=1']
    for source, destination, writable in mounts:
        command += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination + ('' if writable else ',readonly')]
    command += ['--entrypoint', '/usr/bin/python3', c.IMAGE, '/diag-control/diagnose_kodi_keyflag_loader.py', '--inside']
    cid = c.run(command, capture_output=True, timeout=30).stdout.strip()
    try:
        description = c.inspect_owned(cid)
        h = description['HostConfig']
        assert h['Memory'] == h['MemorySwap'] == 1073741824 and h['NanoCpus'] == 1000000000
        assert h['NetworkMode'] == 'none' and h['ReadonlyRootfs'] and not h.get('Privileged')
        assert not h.get('Devices') and not h.get('DeviceRequests')
        assert {m['Destination']: (m['Source'], m['RW']) for m in description['Mounts'] if m['Type'] == 'bind'} == {d: (str(s), w) for s, d, w in mounts}
        c.dump(OUTPUT / 'container-before.json', description)
        c.run(['docker', 'start', '-a', cid], timeout=90)
    finally:
        c.dump(OUTPUT / 'container-after.json', c.cleanup_owned(cid))
        print('diagnostic_cid=' + cid)


if __name__ == '__main__':
    inside() if sys.argv[1:] == ['--inside'] else host()
