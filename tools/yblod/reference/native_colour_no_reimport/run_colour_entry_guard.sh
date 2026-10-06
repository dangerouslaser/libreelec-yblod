#!/bin/sh
set -eu
test "$#" = 3 || test "$#" = 5
job=$1
binary=$2
expected=$3
source_width=${4:-64}
source_height=${5:-64}
export SOURCE_WIDTH="$source_width" SOURCE_HEIGHT="$source_height"
test -d "$job"
test -z "$(ls -A "$job")"
test "$(sha256sum "$binary" | cut -d' ' -f1)" = "$expected"
group=$(awk -F: '$1=="0" {print $3}' /proc/self/cgroup)
cgroup="/sys/fs/cgroup$group"
test "$(cat "$cgroup/memory.max")" = 536870912
test "$(cat "$cgroup/memory.swap.max")" = 0
awk '$1=="max" || $1>$2 {exit 1}' "$cgroup/cpu.max"
cd "$job"
status=0
for phase in before after; do
  for field in memory.peak memory.events memory.swap.current; do
    cp "$cgroup/$field" "$phase-$field"
  done
  sha256sum "$binary" /usr/lib/libEGL.so.1 /usr/lib/libGLESv2.so.2 \
    /usr/lib/libEGL_mesa.so.0 /usr/lib/libgallium-26.2.4.so > "$phase-hashes.txt"
  systemctl show kodi -p ActiveState -p MainPID > "$phase-kodi.txt"
  test "$(systemctl show kodi -p ActiveState --value)" = active
  pid=$(systemctl show kodi -p MainPID --value)
  awk '{print $22}' "/proc/$pid/stat" > "$phase-kodi-startticks.txt"
  python3 - "$phase-active-players.json" <<'PY'
import json, sys, urllib.request
payload = json.dumps(dict(jsonrpc='2.0', method='Player.GetActivePlayers', id=1)).encode()
req = urllib.request.Request('http://127.0.0.1:8080/jsonrpc', payload,
                            {'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=5) as response:
    data = json.load(response)
with open(sys.argv[1], 'x') as output:
    json.dump(data, output)
assert data.get('result') == [] and 'error' not in data
PY
  if test "$phase" = before; then
    set +e
    "$binary" /dev/dri/renderD128 "$job/synthetic-rgb-checkpoint.f32" "$source_width" "$source_height" > result.json 2> stderr.txt
    status=$?
    set -e
    printf '%s\n' "$status" > probe-exit.txt
  fi
done
for field in hashes.txt kodi.txt kodi-startticks.txt; do
  test "$(sha256sum "before-$field" | cut -d' ' -f1)" = "$(sha256sum "after-$field" | cut -d' ' -f1)"
done
awk '$2!=0 {exit 1}' "$cgroup/memory.events"
test "$(cat "$cgroup/memory.swap.current")" = 0
cat result.json
test "$status" = 0
python3 - <<'PY'
import json, os
from pathlib import Path
r = json.loads(Path('result.json').read_text())
assert r['complete'] and r['cleanup_complete']
assert r['rgb_float_values_bit_compared'] == 3840 * 2160 * 4
assert r['failure_checks'] == 2
assert 128 <= r['packet_words_bit_compared'] <= 512
assert r['packet_words_bit_compared'] % 128 == 0
assert r['synthetic_source_size'] == [int(os.environ['SOURCE_WIDTH']),int(os.environ['SOURCE_HEIGHT'])]
assert r['full_output_size'] == [3840,2160]
print('Synthetic old/new colour entry output and packet check PASS')
PY
