"""Private on-target identity observations; never print media fingerprints/paths."""
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path
import stat


def fingerprint(path):
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Regular private source/artifact required')
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    identity = tuple(getattr(before, key) for key in fields)
    if identity != tuple(getattr(after, key) for key in fields):
        raise ValueError('File changed during private fingerprint')
    return identity, digest.hexdigest()


def source_stat(path):
    with Path(path).open('rb') as stream:
        value = os.fstat(stream.fileno())
        if not stat.S_ISREG(value.st_mode):
            raise ValueError('Regular private movie source required')
        return tuple(getattr(value, key) for key in
                     ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


class DRMVersion(ctypes.Structure):
    _fields_ = [('major', ctypes.c_int), ('minor', ctypes.c_int), ('patch', ctypes.c_int),
                ('name_len', ctypes.c_size_t), ('name', ctypes.c_void_p),
                ('date_len', ctypes.c_size_t), ('date', ctypes.c_void_p),
                ('desc_len', ctypes.c_size_t), ('desc', ctypes.c_void_p)]


def gpu_identity(node):
    node = Path(node).resolve(strict=True)
    info = node.stat()
    if not stat.S_ISCHR(info.st_mode) or not node.name.startswith('renderD'):
        raise ValueError('Actual DRM render character device required')
    sysdevice = Path('/sys/dev/char') / f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' / 'device'
    pci = sysdevice.resolve(strict=True)
    vendor = (pci / 'vendor').read_text().strip()
    device = (pci / 'device').read_text().strip()
    driver = (pci / 'driver').resolve(strict=True).name
    name = ctypes.create_string_buffer(128)
    version = DRMVersion(name_len=len(name), name=ctypes.addressof(name))
    ioctl = (3 << 30) | (ctypes.sizeof(version) << 16) | (ord('d') << 8)
    with node.open('rb', buffering=0) as stream:
        fcntl.ioctl(stream.fileno(), ioctl, version)
    if vendor != '0x8086' or driver != 'i915' or name.value != b'i915':
        raise ValueError('Observed Intel i915 target required')
    return dict(rdev=info.st_rdev, pci=str(pci), vendor=vendor, device=device,
                driver=driver, ioctl_driver=name.value.decode('ascii'))


def process_gpu_client(pid, node):
    expected = Path(node).stat().st_rdev
    rows = []
    for entry in (Path('/proc') / str(pid) / 'fd').iterdir():
        try:
            info = entry.stat()
            if not stat.S_ISCHR(info.st_mode) or info.st_rdev != expected:
                continue
            text = (Path('/proc') / str(pid) / 'fdinfo' / entry.name).read_text()
        except FileNotFoundError:
            continue
        fields = dict(line.split(':', 1) for line in text.splitlines() if ':' in line)
        if fields.get('drm-driver', '').strip() == 'i915' and 'drm-client-id' in fields:
            rows.append({key: value.strip() for key, value in fields.items() if key.startswith('drm-')})
    if not rows:
        raise ValueError('Actual probe DRM client association missing')
    return rows


def snapshot(input_path, binary, runtime_files, driver_path, node):
    # Movie identity is stat-level only, not a claim of immutable content.
    return dict(host=hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
        gpu=gpu_identity(node), input=source_stat(input_path), binary=fingerprint(binary),
        runtime={name: fingerprint(path) for name, path in runtime_files.items()},
        driver=fingerprint(driver_path))


def mapped_libraries(pid, runtime_files, driver_path):
    allowed = {str(Path(path).resolve(strict=True)) for path in runtime_files.values()}
    allowed.add(str(Path(driver_path).resolve(strict=True)))
    observed = set()
    for line in (Path('/proc') / str(pid) / 'maps').read_text().splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6 or not parts[5].startswith('/'):
            continue
        path = parts[5]
        if '.so' not in Path(path).name:
            continue
        if path.endswith(' (deleted)') or str(Path(path).resolve(strict=True)) not in allowed:
            raise ValueError('Mapped library outside the exact isolated closure/current driver')
        observed.add(Path(path).name)
    for prefix in ('libavcodec.so.', 'libavformat.so.', 'libavutil.so.',
                   'libvpl.so.', 'libmfx-gen.so.', 'iHD_drv_video.so'):
        if not any(name.startswith(prefix) for name in observed):
            raise ValueError('Actual required hardware route library not mapped')
    return True


def qualify(before, after, expected_host_gpu, expected_binary_sha, expected_runtime_sha,
            expected_driver_sha, actual_client_rows, resources_verified, actual_libraries_verified):
    if before != after:
        raise ValueError('Target/private input/runtime changed across probing')
    if before['host'] != expected_host_gpu['host'] or before['gpu'] != expected_host_gpu['gpu']:
        raise ValueError('Raw probe is not on the independently recorded capture target')
    if before['binary'][1] != expected_binary_sha or before['driver'][1] != expected_driver_sha:
        raise ValueError('Probe artifact or existing driver mismatch')
    if set(before['runtime']) != set(expected_runtime_sha) or any(
            value[1] != expected_runtime_sha[name] for name, value in before['runtime'].items()):
        raise ValueError('Complete candidate runtime fingerprint mismatch')
    if (not actual_client_rows or resources_verified is not True or
            actual_libraries_verified is not True):
        raise ValueError('Actual GPU client and bounded resources required')
    result = {key: True for key in ('target_host_matches_capture_host',
        'physical_gpu_matches_capture_gpu', 'probe_executable_identity_verified',
        'candidate_runtime_identity_verified', 'private_input_identity_verified',
        'identities_unchanged_before_after', 'resource_limits_verified')}
    result['source_identity_scope'] = 'same local file stat/dev/inode/size/mtime/ctime; not content immutability'
    return result
