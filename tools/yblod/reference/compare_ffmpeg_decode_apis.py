"""Private-input, scalar-only resident VAAPI/QSV decode ABBA on an idle host."""
import argparse
import hashlib
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.request


def rpc(method, params=None):
    query = dict(jsonrpc='2.0', method=method, params=params or {}, id=1)
    request = urllib.request.Request('http://127.0.0.1:8086/jsonrpc',
        json.dumps(query).encode(), {'Content-Type': 'application/json'})
    result = json.load(urllib.request.urlopen(request, timeout=3))
    if 'error' in result:
        raise RuntimeError('Kodi read-only RPC failed')
    return result['result']


def require_idle():
    if rpc('Player.GetActivePlayers'):
        raise RuntimeError('User playback is active; no decode benchmark allowed')


def input_file(movie_id, title):
    row = rpc('VideoLibrary.GetMovieDetails', dict(movieid=movie_id, properties=['file']))['moviedetails']
    if row.get('title', row.get('label')) != title:
        raise RuntimeError('Unexpected movie identity')
    private = Path(row['file'])
    if not private.is_absolute():
        raise RuntimeError('Only local mounted media is supported')
    if private.is_file():
        return private
    mounts = json.loads(subprocess.check_output(
        ['docker', 'inspect', 'kodi', '--format', '{{json .Mounts}}'], text=True))
    matches = []
    for mount in mounts:
        try:
            relative = private.relative_to(mount['Destination'])
        except ValueError:
            continue
        candidate = Path(mount['Source'])/relative
        if candidate.is_file():
            matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError('Expected one readable unchanged media mount')
    return matches[0]


def source_identity(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def snapshot(pid):
    clients = {}
    for fd in (Path('/proc')/str(pid)/'fdinfo').glob('*'):
        try:
            values = dict(line.split(':', 1) for line in fd.read_text().splitlines() if ':' in line)
        except OSError:
            continue
        if 'drm-client-id' not in values or 'drm-pdev' not in values:
            continue
        key = values['drm-pdev'].strip()+'/'+values['drm-client-id'].strip()
        engines = {name: int(value.split()[0]) for name, value in values.items()
                   if re.fullmatch(r'drm-engine-(render|copy|video|video-enhance|compute)', name)}
        if key in clients and clients[key] != engines:
            # Multiple descriptors sampled across a changing counter: keep maximum.
            clients[key] = {name: max(clients[key].get(name, 0), value) for name, value in engines.items()}
        else:
            clients[key] = engines
    return time.monotonic_ns(), clients


def gpu_metrics(samples):
    accumulated = {}
    covered = 0
    intervals = 0
    for (start, a), (end, b) in zip(samples, samples[1:]):
        if not a or set(a) != set(b) or end <= start or any(set(a[key]) != set(b[key]) for key in a):
            continue
        delta = {}
        for client in a:
            for engine in a[client]:
                difference = b[client][engine]-a[client][engine]
                if difference < 0:
                    raise RuntimeError('DRM client counter reset')
                delta[engine] = delta.get(engine, 0)+difference
        covered += end-start
        intervals += 1
        for engine, value in delta.items():
            accumulated[engine] = accumulated.get(engine, 0)+value
    if intervals < 2 or covered < 2_000_000_000 or not accumulated:
        raise RuntimeError('Insufficient stable FFmpeg DRM-client observation')
    if accumulated.get('drm-engine-video', 0) <= 0:
        raise RuntimeError('No actual FFmpeg video-engine activity was observed')
    return dict(covered_seconds=covered/1e9, valid_intervals=intervals,
                sampled_engine_seconds={key.removeprefix('drm-engine-'): value/1e9
                                        for key, value in accumulated.items()},
                engine_activity_percent={key.removeprefix('drm-engine-'): 100*value/covered
                                         for key, value in accumulated.items()},
                scope='Deduplicated FFmpeg DRM-client engine time over stable sampled intervals; not whole-GPU utilization.')


def command(api, seconds, seek):
    args = ['/opt/ffmpeg9/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'verbose', '-nostats',
            '-init_hw_device', 'vaapi=va:/dev/dri/renderD128']
    if api == 'qsv':
        args += ['-init_hw_device', 'qsv=qs@va']
    args += ['-hwaccel', api, '-hwaccel_device', 'qs' if api == 'qsv' else 'va',
             '-hwaccel_output_format', api, '-threads', '1', '-c:v', 'hevc_qsv' if api == 'qsv' else 'hevc']
    if api == 'qsv':
        args += ['-async_depth', '4']
    return args+['-ss', str(seek), '-i', '/input/source.mkv', '-t', str(seconds), '-map', '0:v:0',
        '-an', '-sn', '-dn', '-fps_mode', 'passthrough', '-c:v', 'wrapped_avframe',
        '-progress', 'pipe:1', '-f', 'null', '-']


def container_memory(name):
    row = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]
    config = row['HostConfig']
    if config['Memory'] != 536870912 or config['MemorySwap'] != 536870912 or config['NanoCpus'] != 1000000000:
        raise RuntimeError('Unexpected decode container resource limits')
    pid = row['State']['Pid']
    if not pid:
        return None
    control = (Path('/proc')/str(pid)/'cgroup').read_text().splitlines()
    unified = [line.split(':', 2)[2] for line in control if line.startswith('0::')]
    if len(unified) != 1:
        raise RuntimeError('Missing unified decode-container resource accounting')
    root = Path('/sys/fs/cgroup')/unified[0].lstrip('/')
    events = dict(line.split() for line in (root/'memory.events').read_text().splitlines())
    if any(int(events.get(key, 0)) for key in ('max', 'high', 'oom', 'oom_kill')):
        raise RuntimeError('Decode memory allocation limit/throttling event')
    return dict(memory_peak_bytes=int((root/'memory.peak').read_text()),
                memory_swap_current_bytes=int((root/'memory.swap.current').read_text()),
                events={key: int(events.get(key, 0)) for key in ('max', 'high', 'oom', 'oom_kill')},
                cpu_throttled_intervals=int(dict(line.split() for line in (root/'cpu.stat').read_text().splitlines())['nr_throttled']))


def run_case(api, path, seconds, seek, image, name):
    require_idle()
    measured = ['docker', 'run', '--name', name, '--memory=512m', '--memory-swap=512m',
        '--cpus=1', '--network=none', '--device=/dev/dri/renderD128', '--read-only',
        '--tmpfs=/tmp:rw,nosuid,size=32m', '-e', 'XDG_CACHE_HOME=/tmp/.cache',
        '-v', str(path)+':/input/source.mkv:ro', '--entrypoint=/bin/sh',
        image, '-c', '/usr/bin/time -f "__YB_TIME__ %e %U %S %M %x" "$@"; status=$?; sleep 1; exit "$status"',
        'ffmpeg-decode']+command(api, seconds, seek)
    process = subprocess.Popen(measured, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = []
    reader = threading.Thread(target=lambda: output.append(process.communicate()), daemon=True)
    reader.start()
    samples = []
    started = time.monotonic()
    last_idle = started
    pid = None
    memory = None
    try:
        while process.poll() is None:
            if time.monotonic()-started > 120:
                raise RuntimeError('Bounded decode timeout')
            if time.monotonic()-last_idle >= 1:
                require_idle()
                last_idle = time.monotonic()
            if pid is None:
                try:
                    row = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True,
                        stderr=subprocess.DEVNULL))[0]
                    parent = row['State']['Pid']
                    child_file = Path(f'/proc/{parent}/task/{parent}/children')
                    children = child_file.read_text().split()
                    children += [grandchild for child in list(children) for grandchild in
                        Path(f'/proc/{child}/task/{child}/children').read_text().split()]
                    matches = [int(child) for child in children if Path(f'/proc/{child}/comm').read_text().strip() == 'ffmpeg']
                except (OSError, subprocess.CalledProcessError):
                    matches = []
                if len(matches) == 1:
                    pid = matches[0]
            if pid is not None:
                samples.append(snapshot(pid))
                latest_memory = container_memory(name)
                if latest_memory is not None:
                    memory = latest_memory
            time.sleep(.2)
    except BaseException:
        if process.poll() is None:
            if pid is not None:
                os.kill(pid, signal.SIGTERM)
            else:
                subprocess.run(['docker', 'stop', '--time', '10', name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        reader.join(10)
        raise
    reader.join(5)
    if not output or process.returncode != 0:
        raise RuntimeError('Decode process failed; no performance qualification')
    stdout, stderr = output[0]
    if len(stdout)+len(stderr) > 4*1024*1024:
        raise RuntimeError('Unexpected diagnostic volume')
    if re.search(r'Error while decoding|Invalid data found|Failed to|Cannot allocate|out of memory', stderr, re.I):
        raise RuntimeError('Decode or allocation error; no performance qualification')
    if not re.search(r'Video: wrapped_avframe[^\n]*\b'+api+r'\b', stderr):
        raise RuntimeError('Resident hardware output was not verified')
    progress = dict(line.split('=', 1) for line in stdout.splitlines() if '=' in line)
    if (progress.get('progress') != 'end' or int(progress.get('frame', 0)) < 4000 or
            int(progress.get('out_time_us', 0)) < 179_000_000):
        raise RuntimeError('Incomplete requested decode scene')
    if progress.get('dup_frames') != '0' or progress.get('drop_frames') != '0':
        raise RuntimeError('Frame duplication/drop counter failed passthrough qualification')
    timer = re.search(r'__YB_TIME__ ([\d.]+) ([\d.]+) ([\d.]+) (\d+) (\d+)', stderr)
    if not timer or timer[5] != '0':
        raise RuntimeError('Missing completed process accounting')
    elapsed, user, system = map(float, timer.group(1, 2, 3))
    state = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]['State']
    if state['OOMKilled'] or state['ExitCode'] != 0 or not memory or memory['memory_swap_current_bytes']:
        raise RuntimeError('Decode container memory/process qualification failed')
    return dict(api=api, completed_frames=int(progress['frame']),
        duplicate_frames=0, dropped_frames=0,
        output_time_microseconds=int(progress['out_time_us']),
        output_time_seconds=int(progress['out_time_us'])/1e6, wall_seconds=elapsed,
        process_cpu_seconds=user+system, process_cpu_percent_one_core=100*(user+system)/elapsed,
        maximum_rss_bytes=int(timer[4])*1024, hardware_resident_output_verified=True,
        gpu=gpu_metrics(samples), memory=memory, decode_process_exit_code=0,
        retained_container=name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--movie-id', type=int, default=3391, choices=(3391, 3955))
    parser.add_argument('--seconds', type=int, default=180, choices=(180,))
    parser.add_argument('--seek-seconds', type=int, default=1200, choices=(1200,))
    parser.add_argument('--image', default='yblod-ffmpeg9-decode:9.0.2')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report and (not args.report.parent.is_dir() or args.report.exists()):
        raise RuntimeError('Fresh scalar report destination required')
    require_idle()
    title = {3391: 'Saving Private Ryan', 3955: 'Trainspotting'}[args.movie_id]
    path = input_file(args.movie_id, title)
    if path.suffix.lower() not in ('.mkv', '.mp4', '.m2ts', '.ts'):
        raise RuntimeError('Expected local owned video media')
    original = source_identity(path)
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.image], text=True))[0]['Id']
    version = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--memory=512m',
        '--memory-swap=512m', '--cpus=1', image, '-version'], text=True)
    if not version.startswith('ffmpeg version 9.0.2 ') or '--enable-libvpl' not in version or '--enable-vaapi' not in version:
        raise RuntimeError('Expected the same FFmpeg9.0.2 VAAPI+libvpl container binary')
    binary = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--memory=512m',
        '--memory-swap=512m', '--cpus=1', '--entrypoint=sha256sum', image,
        '/opt/ffmpeg9/bin/ffmpeg'], text=True).split()[0]
    streams = json.loads(subprocess.check_output(['docker', 'run', '--rm', '--network=none',
        '--memory=512m', '--memory-swap=512m', '--cpus=1', '-v', str(path)+':/input/source.mkv:ro',
        '--entrypoint=/opt/ffmpeg9/bin/ffprobe', image, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,avg_frame_rate', '-of', 'json',
        '/input/source.mkv'], text=True, stderr=subprocess.DEVNULL, timeout=30))['streams']
    if (len(streams) != 1 or streams[0].get('codec_name') != 'hevc' or
            streams[0].get('width') != 3840 or streams[0].get('height') != 2160 or
            streams[0].get('pix_fmt') != 'yuv420p10le'):
        raise RuntimeError('Expected the same 4K ten-bit HEVC source video')
    rate = Fraction(streams[0].get('avg_frame_rate', '0/1'))
    if not 0 < rate <= 240:
        raise RuntimeError('Expected a valid positive source frame-rate rational')
    packages = subprocess.check_output(['docker', 'run', '--rm', '--network=none',
        '--memory=512m', '--memory-swap=512m', '--cpus=1', '--entrypoint=dpkg-query', image,
        '-W', '-f', '${Package}=${Version}\n', 'libvpl2', 'libmfx-gen1.2',
        'intel-media-va-driver', 'libva2', 'libva-drm2'], text=True)
    runtime_versions = dict(line.split('=', 1) for line in packages.splitlines())
    cases = []
    for order, api in enumerate(('vaapi', 'qsv', 'qsv', 'vaapi'), 1):
        if source_identity(path) != original:
            raise RuntimeError('Source file changed')
        print(json.dumps(dict(status='begin', order=order, api=api)), flush=True)
        row = run_case(api, path, args.seconds, args.seek_seconds, image,
                       'yblod-ffmpeg9-'+api+'-'+str(os.getpid())+'-'+str(order))
        row['order'] = order
        cases.append(row)
        print(json.dumps(dict(status='case_complete', **row)), flush=True)
    if (source_identity(path) != original or len({row['completed_frames'] for row in cases}) != 1 or
            len({row['output_time_microseconds'] for row in cases}) != 1):
        raise RuntimeError('Source, completed frame counts or output endpoint differed')
    result = dict(schema='yblod.ffmpeg-decode-api-scalar-results.v1',
        content=title, movie_id=args.movie_id, seconds_of_source=180, seek_seconds=1200,
        ffmpeg_version=version.splitlines()[0], ffmpeg_configuration=version.splitlines()[2],
        ffmpeg_binary_sha256=binary, container_image_id=image, cases=cases,
        container_runtime_versions=runtime_versions,
        source_stream={key: streams[0][key] for key in ('codec_name','width','height','pix_fmt','avg_frame_rate')},
        source_frame_rate=dict(numerator=rate.numerator, denominator=rate.denominator),
        resource_limits=dict(memory_bytes=536870912, extra_swap_bytes=0, cpus=1, network='none'),
        same_input_unchanged=True, same_ffmpeg_binary=True,
        scopes=['Maximum-throughput base video decode to resident wrapped-frame null sink; no audio/subtitles, enhancement-layer reconstruction, Dolby composition, display or encode.',
                'Disposable minimal FFmpeg9.0.2 container is separate from Kodi patched FFmpeg9.0.2 and the full DV pipeline.',
                'Both APIs use the same Intel render node; QSV derives from VAAPI and uses async_depth4.',
                'Each decode container is limited to512MiB/no swap/one CPU; a separate lightweight host observer is not included in FFmpeg process accounting. CPU quota can constrain throughput.',
                'No pixel equivalence or full-playback efficiency claim; no private paths, logs, frames or media hashes exported.'])
    if args.report:
        with args.report.open('x') as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Source/media paths and private FFmpeg diagnostics must stay on host.
        message = str(error) if type(error) is RuntimeError else 'Host/setup accounting failed'
        print(json.dumps(dict(status='failed', error_type=type(error).__name__, reason=message)), flush=True)
        raise SystemExit(1)
