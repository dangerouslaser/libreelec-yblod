"""Copy completed private captures and verify all four files at three locations.

No playback, configuration changes or deletion. Run only after captures finish.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess

FILES = ('request', 'output.rgba', 'metadata.bin', 'frame.json')
CAPTURE_ROOT = PurePosixPath('/storage/dvbridge-output-captures')
FRAME = re.compile(r'frame-[A-Za-z0-9_-]+\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*\Z')


def absolute_path(value):
    path = PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path) != value:
        raise ValueError('Expected canonical absolute path')
    return path


def validate_report(report, sha, movie_id=None, title=None, file_basename=None):
    if not SHA.fullmatch(sha):
        raise ValueError('Expected complete lowercase SHA256')
    before, after = report['identity_before'], report['identity_after']
    if before != after or before.get('binary_sha256') != sha:
        raise ValueError('Capture binary/process identity mismatch')
    for field in ('pid', 'service_pid', 'start_ticks'):
        if type(before.get(field)) is not int or before[field] <= 0:
            raise ValueError('Invalid capture process identity')
    if set(report['shutdown'].splitlines()) != {'ActiveState=inactive', 'Result=success', 'MainPID=0'}:
        raise ValueError('Capture shutdown was not clean')
    if file_basename is not None:
        if movie_id is not None or title is not None or not file_basename or PurePosixPath(file_basename).name != file_basename or file_basename in ('.', '..'):
            raise ValueError('Invalid file identity arguments')
        if 'movie' in report or report.get('file', {}).get('basename') != file_basename:
            raise ValueError('Unexpected file identity')
    else:
        movie = report.get('movie', {})
        if type(movie_id) is not int or movie_id <= 0 or not title or 'file' in report or movie.get('id') != movie_id or movie.get('title') != title:
            raise ValueError('Unexpected movie identity')
    frames = report['frames']
    if not isinstance(frames, list) or not 1 <= len(frames) <= 16:
        raise ValueError('Expected 1..16 frames')
    seen = set()
    for frame in frames:
        path = absolute_path(frame['directory'])
        if path.parent != CAPTURE_ROOT or not FRAME.fullmatch(path.name) or path.name in seen:
            raise ValueError('Unexpected capture directory')
        seen.add(path.name)
        if frame.get('width') != 3840 or frame.get('height') != 2160:
            raise ValueError('Unexpected capture dimensions')
    return frames


def local_hash(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Archive must contain regular files')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            size += len(chunk)
            digest.update(chunk)
    return dict(size=size, sha256=digest.hexdigest())


REMOTE_HASH = '''import hashlib,json,os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1])
if not p.is_absolute() or p.resolve()!=p: raise RuntimeError("symlink/noncanonical directory")
result={}
for name in ("request","output.rgba","metadata.bin","frame.json"):
 f=p/name
 if not stat.S_ISREG(f.lstat().st_mode): raise RuntimeError("not regular")
 size=f.stat().st_size
 if name=="request" and not 0<size<=256: raise RuntimeError("request size")
 if name=="metadata.bin" and not 0<size<=1048576: raise RuntimeError("metadata size")
 digest=hashlib.sha256();size=0
 with f.open("rb") as source:
  for chunk in iter(lambda:source.read(1048576),b""):
   size+=len(chunk);digest.update(chunk)
 result[name]={"size":size,"sha256":digest.hexdigest()}
print(json.dumps(result))
'''


def command(*args):
    return subprocess.check_output(args, text=True, timeout=180)


def remote(host, *args):
    if not HOST.fullmatch(host):
        raise ValueError('Invalid SSH host')
    return command('ssh', '-o', 'BatchMode=yes', host, shlex.join(args))


def remote_hash(host, directory):
    return json.loads(remote(host, 'python3', '-c', REMOTE_HASH, str(directory)))


def archive(args):
    report_path = absolute_path(args.vm_report)
    report_root = absolute_path(args.expected_report_root)
    if report_path.parent != report_root or not re.fullmatch(r'[A-Za-z0-9_-]+\.json', report_path.name):
        raise ValueError('Report outside expected root')
    archive_root = Path(args.local_archive)
    if not archive_root.is_absolute() or archive_root.exists() or archive_root.parent.resolve() != archive_root.parent:
        raise ValueError('Local archive must be fresh beneath a canonical existing parent')
    for parent in archive_root.parents:
        if (parent/'.git').exists() and 'target' not in archive_root.relative_to(parent).parts:
            raise ValueError('Refusing media archive in public source worktree')
    ollie_root = absolute_path(args.ollie_archive)
    if ollie_root == PurePosixPath('/') or len(ollie_root.parts) < 4:
        raise ValueError('Ollie archive path too broad')
    # Bounded JSON read; reject report symlinks and unexpectedly large reports.
    report_code = 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); assert p.resolve()==p and p.is_file() and p.stat().st_size<=1048576; print(p.read_text())'
    report = json.loads(remote(args.vm_host, 'python3', '-c', report_code, str(report_path)))
    frames = validate_report(report, args.binary_sha256, args.movie_id, args.expected_title, args.expected_file_basename)
    archive_root.mkdir()
    mkdir_code = '''import pathlib,sys
p=pathlib.Path(sys.argv[1])
assert p.parent.resolve()==p.parent
for ancestor in p.parents:
 if (ancestor/".git").exists() and "target" not in p.relative_to(ancestor).parts:
  raise RuntimeError("refusing media archive in public source worktree")
p.mkdir()
'''
    remote(args.ollie_host, 'python3', '-c', mkdir_code, str(ollie_root))
    verified = []
    for frame in frames:
        source = absolute_path(frame['directory'])
        baseline = remote_hash(args.vm_host, source)
        if baseline['output.rgba']['size'] != 3840*2160*4 or not 0 < baseline['frame.json']['size'] <= 4096:
            raise ValueError('Unexpected capture file size')
        if not 0 < baseline['request']['size'] <= 256 or not 0 < baseline['metadata.bin']['size'] <= 1024*1024:
            raise ValueError('Unexpected request or metadata size')
        destination = archive_root/source.name
        destination.mkdir()
        command('scp', '-q', '-o', 'BatchMode=yes',
                *(f'{args.vm_host}:{source/name}' for name in FILES), str(destination))
        local = {name: local_hash(destination/name) for name in FILES}
        expected_frame = {key: value for key, value in frame.items() if key != 'directory'}
        if json.loads((destination/'frame.json').read_text()) != expected_frame:
            raise ValueError('Frame JSON does not match report association')
        if baseline != local or remote_hash(args.vm_host, source) != baseline:
            raise ValueError('VM capture changed or local copy mismatch')
        remote_directory = ollie_root/source.name
        remote(args.ollie_host, 'python3', '-c', mkdir_code, str(remote_directory))
        command('scp', '-q', '-o', 'BatchMode=yes',
                *(str(destination/name) for name in FILES), f'{args.ollie_host}:{remote_directory}/')
        if remote_hash(args.ollie_host, remote_directory) != baseline:
            raise ValueError('Ollie archive mismatch')
        verified.append(dict(frame=source.name, pts=frame.get('pts'), native=frame.get('native'),
                             native_planar=frame.get('native_planar'), direct_packed=frame.get('direct_packed'),
                             qsv_mode=frame.get('qsv_mode'), files=baseline))
    manifest = dict(schema='yblod.capture-archive.v1', complete=True, binary_sha256=args.binary_sha256,
                    frames=verified, vm_files_deleted=False)
    identity_key = 'file' if args.expected_file_basename is not None else 'movie'
    manifest[identity_key] = report[identity_key]
    with (archive_root/'archive-verification.json').open('x') as output:
        json.dump(manifest, output, indent=2)
    print(json.dumps(manifest, indent=2))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('vm-host', 'vm-report', 'expected-report-root', 'binary-sha256',
                 'local-archive', 'ollie-host', 'ollie-archive'):
        parser.add_argument('--'+name, required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--movie-id', type=int)
    identity.add_argument('--expected-file-basename')
    parser.add_argument('--expected-title')
    args = parser.parse_args(argv)
    if args.movie_id is not None and not args.expected_title:
        parser.error('--movie-id requires --expected-title')
    if args.expected_file_basename is not None and args.expected_title is not None:
        parser.error('--expected-file-basename does not accept --expected-title')
    archive(args)


if __name__ == '__main__':
    main()
