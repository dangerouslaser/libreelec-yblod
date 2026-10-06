"""Build a private isolated runtime from active SDK SONAMEs, never a driver overlay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOTS = ('libavcodec.so', 'libavdevice.so', 'libavfilter.so', 'libavformat.so',
         'libavutil.so', 'libswresample.so', 'libswscale.so', 'libvpl.so', 'libmfx-gen.so')


def digest(path, destination=None):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
            if destination is not None:
                destination.write(block)
    return value.hexdigest()


def packaged(name):
    return any(name == root or name.startswith(root + '.') for root in ROOTS)


def resolve(path, sdk, mapped_sdk):
    path = Path(path)
    seen = set()
    while path.is_symlink():
        if path in seen:
            raise ValueError('SDK symlink cycle')
        seen.add(path)
        target = Path(os.readlink(path))
        if target.is_absolute():
            try:
                target = sdk / target.relative_to(mapped_sdk)
            except ValueError as error:
                raise ValueError('Absolute dependency link outside SDK') from error
        else:
            target = path.parent / target
        path = Path(os.path.abspath(target))
    path = path.resolve(strict=True)
    if not path.is_relative_to(sdk.resolve()) or not path.is_file():
        raise ValueError('Dependency outside authoritative SDK')
    return path


def elf(path, readelf):
    result = subprocess.run([readelf, '-h', '-d', str(path)], check=True,
                            capture_output=True, text=True).stdout
    if 'ELF64' not in result or 'Advanced Micro Devices X86-64' not in result:
        raise ValueError('Only target x86_64 ELF64 artifacts accepted')
    needed = re.findall(r'\(NEEDED\).*\[([^]]+)\]', result)
    soname = re.findall(r'\(SONAME\).*\[([^]]+)\]', result)
    if len(soname) > 1:
        raise ValueError('Ambiguous ELF SONAME')
    versions = subprocess.run([readelf, '-W', '--version-info', str(path)], check=True,
                              capture_output=True, text=True).stdout
    required, current = {}, None
    in_needs = False
    for line in versions.splitlines():
        if line.startswith('Version needs section'):
            in_needs = True
        if not in_needs:
            continue
        match = re.search(r'File: (\S+)', line)
        if match:
            current = match.group(1)
            required[current] = []
        match = re.search(r'Name: (\S+)', line)
        if match and current:
            required[current].append(match.group(1))
    return needed, soname[0] if soname else None, required


def plan(sdk, mapped_sdk, readelf, target):
    if (not isinstance(target, dict) or target.get('actual_target_identity_verified') is not True or
            target.get('existing_driver_identity_verified') is not True or
            not isinstance(target.get('libraries'), dict)):
        raise ValueError('Observed unchanged target ELF dependency manifest required')
    sdk = sdk.resolve(strict=True)
    dirs = [sdk / 'x86_64-libreelec-linux-gnu/sysroot/usr/lib',
            sdk / 'x86_64-libreelec-linux-gnu/lib']
    def find(name):
        if '/' in name or name in ('.', '..') or 'iHD' in name:
            raise ValueError('Unsafe dependency or forbidden driver overlay')
        paths = [p / name for p in dirs if (p / name).exists() or (p / name).is_symlink()]
        resolved = {resolve(p, sdk, mapped_sdk) for p in paths}
        if len(resolved) != 1:
            raise ValueError('Missing/ambiguous SDK dependency: ' + name)
        return resolved.pop()
    pending = list(ROOTS)
    names, files, external = {}, {}, {}
    while pending:
        name = pending.pop()
        if name in names:
            continue
        if not packaged(name):
            item = target['libraries'].get(name)
            if (not isinstance(item, dict) or item.get('elf64_x86_64') is not True or
                    item.get('actual_resolution_verified') is not True or
                    not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')) or
                    not isinstance(item.get('defined_versions'), list)):
                raise ValueError('Missing actual target dependency: ' + name)
            external[name] = item
            continue
        path = find(name)
        if path.name == 'iHD_drv_video.so':
            raise ValueError('Driver packaging forbidden')
        names[name] = path.name
        if path.name in files:
            if files[path.name]['source'] != path:
                raise ValueError('Conflicting artifact basenames')
            continue
        needed, soname, versions = elf(path, readelf)
        files[path.name] = dict(source=path, needed=needed, soname=soname,
            required_versions=versions, sha256=digest(path))
        if soname:
            if soname in names and names[soname] != path.name:
                raise ValueError('Conflicting SONAME')
            names[soname] = path.name
        pending.extend(needed)
    for item in files.values():
        for dependency, required in item['required_versions'].items():
            if not packaged(dependency):
                available = external.get(dependency, {}).get('defined_versions', [])
                if not set(required).issubset(set(available)):
                    raise ValueError('Incompatible existing target ELF versions: ' + dependency)
    return names, files, external


def package(sdk, mapped_sdk, readelf, output, target, maximum_unpacked_bytes):
    if output.exists():
        raise ValueError('Fresh private artifact required')
    names, files, external = plan(sdk, mapped_sdk, readelf, target)
    estimated = sum(item['source'].stat().st_size for item in files.values())
    if type(maximum_unpacked_bytes) is not int or maximum_unpacked_bytes <= 0 or estimated > maximum_unpacked_bytes:
        raise ValueError('Explicit target storage budget exceeded before package write')
    with tempfile.TemporaryDirectory(prefix='el-qsv-runtime-') as temp:
        root = Path(temp)
        libs = root / 'lib'
        libs.mkdir()
        for name, item in files.items():
            with (libs / name).open('xb') as destination:
                if digest(item['source'], destination) != item['sha256']:
                    raise ValueError('SDK changed while packaging')
        for alias, name in names.items():
            if alias != name:
                (libs / alias).symlink_to(name)
        manifest = dict(schema='yblod.el-qsv-runtime.v1', driver_overlay=False,
            core_runtime_overlay=False, existing_target_dependencies=external,
            estimated_unpacked_library_bytes=estimated,
            artifacts={name: {key: value for key, value in item.items() if key != 'source'}
                       for name, item in files.items()}, links=names)
        (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Final output must remain private; no SDK paths are saved in the manifest.
        with output.open('xb') as stream:
            os.chmod(output, 0o600)
            with tarfile.open(fileobj=stream, mode='w') as archive:
                archive.add(root / 'manifest.json', arcname='manifest.json')
                archive.add(libs, arcname='lib')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--mapped-sdk', type=Path, required=True)
    parser.add_argument('--readelf', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-manifest', type=Path, required=True)
    parser.add_argument('--maximum-unpacked-bytes', type=int, required=True)
    args = parser.parse_args()
    package(args.sdk, args.mapped_sdk, args.readelf, args.output,
            json.loads(args.target_manifest.read_text()), args.maximum_unpacked_bytes)


if __name__ == '__main__':
    main()
