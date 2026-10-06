"""Target launch preparation. Execution awaits reviewed live-probe handshake wiring."""
from pathlib import Path
import json
import os
import re
import stat
from capture_scene import rpc
from collect_el_qsv_target_identity import mapped_libraries, process_gpu_client


def handshake_environment(ready, ack, nonce):
    if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{64}', nonce):
        raise ValueError('Fresh 256-bit handshake nonce required')
    for path in (ready, ack):
        path = Path(path)
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise ValueError('Fresh absolute private handshake paths required')
    if Path(ready) == Path(ack):
        raise ValueError('Separate ready and acknowledgement files required')
    return dict(YB_QSV_PROBE_READY=str(ready), YB_QSV_PROBE_ACK=str(ack), YB_QSV_PROBE_NONCE=nonce)


def acknowledge_live_probe(ready, ack, nonce, actual_unit_pid, node, runtime_files, driver):
    info = Path(ready).lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Private regular ready checkpoint required')
    checkpoint = json.loads(Path(ready).read_text())
    if (set(checkpoint) != {'pid', 'nonce'} or type(checkpoint['pid']) is not int or
            type(actual_unit_pid) is not int or actual_unit_pid <= 0 or
            checkpoint['pid'] != actual_unit_pid or checkpoint['nonce'] != nonce):
        raise ValueError('Checkpoint must match actual live systemd unit PID/nonce')
    client = process_gpu_client(actual_unit_pid, node)
    libraries = mapped_libraries(actual_unit_pid, runtime_files, driver)
    # The C hook remains live until it reads exactly these nonce bytes.
    descriptor = os.open(ack, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(nonce.encode('ascii'))
    return client, libraries


def idle_movie_source():
    if rpc('Player.GetActivePlayers') != []:
        raise ValueError('Do not contend with user playback')
    movie = rpc('VideoLibrary.GetMovieDetails',
                {'movieid': 3391, 'properties': ['title', 'file']})['moviedetails']
    path = Path(movie.get('file', ''))
    if movie.get('title') != 'Saving Private Ryan' or not path.is_absolute():
        raise ValueError('Exact local SPR library source required')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise ValueError('Existing nonempty private movie file required')
    if rpc('Player.GetActivePlayers') != []:
        raise ValueError('Playback became active during preparation')
    return path.resolve(strict=True)


def launch_command(unit, binary, runtime, existing_driver, node, seek_us, pts, private_log):
    if not unit.startswith('yblod-qsv-target-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in unit):
        raise ValueError('Explicit dedicated unit name required')
    if type(seek_us) is not int or seek_us != 1200000000 or len(pts) != 3 or any(
            type(p) is not int or not 1200000000 < p <= 1380000000 for p in pts) or pts != sorted(set(pts)):
        raise ValueError('Exact three increasing matched capture timestamps required')
    paths = [Path(p).resolve(strict=True) for p in (binary, runtime, existing_driver, node)]
    binary, runtime, existing_driver, node = paths
    if not runtime.is_dir() or not binary.is_file() or not existing_driver.is_file():
        raise ValueError('Reviewed installed artifacts required')
    private_log = Path(private_log)
    if not private_log.is_absolute() or private_log.exists() or private_log.is_symlink():
        raise ValueError('Fresh private diagnostic file required')
    source = idle_movie_source()
    # Use target loader/driver and target-owned core ABI, never SDK replacements.
    loader = Path('/usr/lib/ld-linux-x86-64.so.2').resolve(strict=True)
    expected = dict(LD_LIBRARY_PATH=str(runtime), ONEVPL_PRIORITY_PATH=str(runtime),
        LIBVA_DRIVER_NAME='iHD', LIBVA_DRIVERS_PATH=str(existing_driver.parent),
        EXPECTED_QSV_LIBVPL=str((runtime / 'libvpl.so.2.17').resolve(strict=True)),
        EXPECTED_QSV_IMPLEMENTATION=str((runtime / 'libmfx-gen.so.1.2.17').resolve(strict=True)),
        EXPECTED_QSV_VA_DRIVER=str(existing_driver))
    command = ['systemd-run', '--wait', '--pipe', '--unit=' + unit,
        '-p', 'MemoryMax=536870912', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
        '-p', 'PrivateNetwork=yes', '-p', 'RuntimeMaxSec=180', '-p', 'UMask=0077',
        '-p', 'StandardError=file:' + str(private_log)]
    for key, value in expected.items():
        command.extend(['--setenv=' + key + '=' + value])
    command.extend([str(loader), '--library-path', str(runtime), str(binary),
                    str(source), str(node), str(seek_us), *(str(p) for p in pts)])
    return command
