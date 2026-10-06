#!/bin/sh
# Run only inside a fresh bounded transient service, never during playback.
set -eu
test "$#" = 7
timer=${YB_GPU_DIAG_TIMER:-0}
case "$timer" in 0|1) ;; *) exit 2 ;; esac
export YB_GPU_DIAG_TIMER="$timer"
case "$0" in /*) guard_path=$0 ;; *) guard_path="$(pwd)/$0" ;; esac
task_dir=$1
binary=$2
shader=$3
input=$4
binary_sha=$5
shader_sha=$6
input_sha=$7
python3 - "$task_dir" "$binary" "$shader" "$input" "$binary_sha" "$shader_sha" "$input_sha" <<'PY'
import hashlib, os, re, stat, sys
from pathlib import Path
directory = Path(sys.argv[1])
if not directory.is_absolute() or any(not Path(p).is_absolute() for p in sys.argv[2:5]):
    raise ValueError('absolute artifact/output paths required')
state = directory.lstat()
if not stat.S_ISDIR(state.st_mode) or state.st_mode & 0o077 or state.st_uid != os.geteuid() or any(directory.iterdir()):
    raise ValueError('fresh owned private directory required')
for path, expected in zip(sys.argv[2:5], sys.argv[5:8]):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or re.fullmatch('[0-9a-f]{64}', expected) is None:
        raise ValueError('regular pinned artifact required')
    with p.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise ValueError('artifact hash differs')
if Path(sys.argv[4]).stat().st_size != 24883200:
    raise ValueError('4K reconstructed Y/Cb/Cr dump extent differs')
PY
group=$(awk -F: '$1=="0" {print $3}' /proc/self/cgroup)
cgroup="/sys/fs/cgroup$group"
test "$(cat "$cgroup/memory.max")" = 536870912
test "$(cat "$cgroup/memory.swap.max")" = 0
test "$(cat "$cgroup/memory.swap.current")" = 0
awk '$2!=0 {exit 1}' "$cgroup/memory.events"
awk '$1=="max" || $1<=0 || $2<=0 || $1>$2 {exit 1}' "$cgroup/cpu.max"
cd "$task_dir"
umask 077
status=0
for phase in before after; do
  for field in memory.max memory.peak memory.events memory.swap.current memory.swap.max cpu.max cpu.stat; do
    cp "$cgroup/$field" "$phase-$field"
  done
  sha256sum "$binary" "$shader" "$input" "$guard_path" \
    /usr/lib/libEGL.so.1 /usr/lib/libEGL_mesa.so.0 /usr/lib/libGLdispatch.so.0 \
    /usr/lib/libgallium-26.2.4.so /usr/lib/libgbm.so.1 /usr/lib/libdrm.so.2 \
    /usr/lib/libc.so.6 /usr/lib/ld-linux-x86-64.so.2 > "$phase-hashes.txt"
  systemctl show kodi -p ActiveState -p MainPID > "$phase-kodi.txt"
  test "$(systemctl show kodi -p ActiveState --value)" = active
  kodi_pid=$(systemctl show kodi -p MainPID --value)
  test "$kodi_pid" -gt 0
  awk '{print $22}' "/proc/$kodi_pid/stat" > "$phase-kodi-startticks.txt"
  python3 - "$phase-active-players.json" "$phase-kodi-bin.json" <<'PY'
import hashlib, json, sys, urllib.request
from pathlib import Path
processes = []
for process in Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        if (process / 'comm').read_text().strip() != 'kodi.bin':
            continue
        fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
        with (process / 'exe').open('rb') as stream:
            binary_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        processes.append(dict(pid=int(process.name), start_ticks=int(fields[19]),
                              executable_sha256=binary_hash))
    except FileNotFoundError:
        continue
if len(processes) != 1:
    raise ValueError('one stable Kodi executable required')
with open(sys.argv[2], 'x') as output:
    json.dump(processes, output, sort_keys=True)
payload = json.dumps(dict(jsonrpc='2.0', method='Player.GetActivePlayers', id=1)).encode()
request = urllib.request.Request('http://127.0.0.1:8080/jsonrpc', payload,
                                 {'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=5) as response:
    result = json.load(response)
with open(sys.argv[1], 'x') as output:
    json.dump(result, output)
if result.get('result') != [] or 'error' in result:
    raise ValueError('active playback or unavailable Kodi RPC')
PY
  if test "$phase" = before; then
    set +e
    YB_COMPARE_WARMUPS=8 YB_COMPARE_SAMPLES=12 \
      "$binary" /dev/dri/renderD128 "$shader" 3840 2160 "$input" \
      > result.json 2> stderr.txt
    status=$?
    set -e
    printf '%s\n' "$status" > probe-exit.txt
  fi
done
for field in hashes.txt kodi.txt kodi-startticks.txt kodi-bin.json; do
  test "$(sha256sum "before-$field" | cut -d' ' -f1)" = "$(sha256sum "after-$field" | cut -d' ' -f1)"
done
test "$(cat "$cgroup/memory.swap.current")" = 0
awk '$2!=0 {exit 1}' "$cgroup/memory.events"
test "$status" = 0
python3 - <<'PY'
import json, os
from pathlib import Path
r = json.loads(Path('result.json').read_text())
assert r['schema'] == 'yblod.gpu-ycc-frame-timer-probe.v1'
assert r['complete'] and r['cleanup_complete'] and r['independent_dyadic_integer_oracle']
assert (r['width'], r['height']) == (3840, 2160)
assert r['full_image_oracle_checks'] == 2
assert r['float_values_bit_compared'] == 3840 * 2160 * 4 * 2
assert r['warmups'] == 8 and r['samples'] == 12
assert r['gpu_timer_query_requested'] == (os.environ['YB_GPU_DIAG_TIMER'] == '1')
fields = ['host_submit_finish_wall_ns', 'host_submit_finish_cpu_ns']
if r['gpu_timer_query_requested']:
    assert r['gpu_timer_extra_fences'] == 0 and r['gpu_timer_extra_waits'] == 0
    fields.append('gpu_elapsed_ns')
else:
    assert 'gpu_elapsed_ns' not in r
for field in fields:
    assert len(r[field]) == 12 and all(type(v) is int and v > 0 for v in r[field])
assert r['linked_workgroup'] in ([8,8,1], [16,8,1], [16,16,1])
print('Guarded YCC timer result and full-image bit-exact oracle PASS')
PY
cat result.json
