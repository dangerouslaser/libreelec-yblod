"""Read-only private target ABI provenance; no runtime installation or media reads."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
from collect_el_qsv_target_identity import gpu_identity


def observe_target(node):
    return dict(host=hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
                gpu=gpu_identity(node))


def collect(names, existing_driver, expected_driver_sha, node, idle_check):
    idle_check()
    capture_target = observe_target(node)
    libraries = {}
    for name in names:
        if not isinstance(name, str) or '/' in name or not name.startswith('lib'):
            raise ValueError('Explicit dependency SONAMEs required')
        path = (Path('/usr/lib') / name).resolve(strict=True)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            header = stream.read(20)
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError('Target library changed during observation')
        valid = (header[:4] == bytes([127, 69, 76, 70]) and header[4] == 2 and
                 header[5] == 1 and int.from_bytes(header[18:20], 'little') == 62)
        if not valid:
            raise ValueError('Target dependency is not x86_64 ELF64')
        versions = subprocess.check_output(['readelf', '-V', str(path)], text=True)
        defined = (versions.split('Version definition section')[-1].split('Version needs section')[0]
                   if 'Version definition section' in versions else '')
        libraries[name] = dict(elf64_x86_64=True, actual_resolution_verified=True,
            sha256=digest.hexdigest(), defined_versions=re.findall(r'Name: (\S+)', defined),
            resolved_basename=path.name)
    sha = hashlib.sha256()
    with Path(existing_driver).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    if sha.hexdigest() != expected_driver_sha:
        raise ValueError('Existing target iHD driver changed')
    if observe_target(node) != capture_target:
        raise ValueError('Actual target host/GPU changed during observation')
    idle_check()
    return dict(schema='yblod.el-qsv-target-dependencies.v1', capture_target=capture_target,
                actual_target_identity_verified=True, existing_driver_identity_verified=True,
                libraries=libraries, existing_driver_sha256=sha.hexdigest(),
                scope='Observed target files and version definitions, not dynamic relocation or hardware qualification')
