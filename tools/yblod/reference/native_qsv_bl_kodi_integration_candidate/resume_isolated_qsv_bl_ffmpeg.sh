#!/bin/sh
set -eu
test "$#" = 2 || {
  echo 'usage: resume_isolated_qsv_bl_ffmpeg.sh SDK_ROOT CONFIGURED_V3_TARGET_DIR' >&2
  exit 2
}
sdk=$(realpath "$1")
target=$2
test -d "$target/ffmpeg-bl-qsv-candidate"
test -f "$target/isolated-ffmpeg-build-results.json"
test ! -e "$target/make.log"
test ! -e "$target/isolated-ffmpeg-make-results.json"
test ! -e "$target/isolated-ffmpeg-make-failure.json"
case "$target" in /*/target/qsv-bl-ffmpeg-isolated-v3-20261006) ;; *) exit 2 ;; esac
test -d "$sdk/build.LibreELEC-Generic.x86_64-13.0-devel/build/ffmpeg-9.0.2"
reference=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
metadata=$(realpath "$reference/../native_qsv_bl_ffmpeg_metadata_candidate")
test -f "$metadata/qsv-bl-metadata-real-init-fix.patch"
image=sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e
container=yblod-qsv-bl-ffmpeg-make-20261006
test "$(awk '/MemAvailable:/ {print $2 * 1024 >= 6442450944}' /proc/meminfo)" = 1
docker image inspect "$image" >/dev/null
id=$(docker create --name "$container" --memory=4g --memory-swap=4g --cpus=1 \
  --network=none --read-only --tmpfs /tmp:rw,nosuid,exec,size=64m \
  --user 0:0 -e CCACHE_DISABLE=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$sdk:/build:ro" -v "$reference:/reference:ro" \
  -v "$metadata:/metadata:ro" -v "$target:/lab:rw" \
  --entrypoint /bin/sh "$image" -c \
  "python3 /reference/resume_isolated_qsv_bl_ffmpeg.py")
case "$id" in ''|*[!a-f0-9]*) exit 1 ;; esac
test "${#id}" = 64
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  running=$(docker inspect --format '{{.State.Running}}' "$id")
  if test "$running" = true; then
    docker stop --time 10 "$id" >/dev/null 2>&1
    docker wait "$id" >/dev/null 2>&1
  fi
  docker inspect "$id" > "$target/make-container-after.json"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker inspect "$id" > "$target/make-container-before.json"
python3 - "$target/make-container-before.json" "$id" "$image" "$sdk" "$reference" "$metadata" "$target" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))[0]
assert d['Id'] == sys.argv[2] and d['Config']['Image'] == sys.argv[3]
assert d['Image'] == sys.argv[3]
h = d['HostConfig']
assert h['Memory'] == 4294967296 and h['MemorySwap'] == 4294967296
assert h['NanoCpus'] == 1000000000 and h['NetworkMode'] == 'none'
assert h['ReadonlyRootfs'] and not h.get('Devices')
expected = {'/build': (sys.argv[4], False), '/reference': (sys.argv[5], False),
            '/metadata': (sys.argv[6], False), '/lab': (sys.argv[7], True)}
binds = {m['Destination']: (m['Source'], m['RW']) for m in d['Mounts'] if m['Type'] == 'bind'}
assert binds == expected
PY
set +e
docker start -a "$id" > "$target/make.log" 2>&1
result=$?
set -e
docker inspect "$id" > "$target/make-container-after.json"
python3 - "$target/make-container-after.json" "$id" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))[0]
assert d['Id'] == sys.argv[2] and not d['State']['Running']
assert d['State']['ExitCode'] == 0 and not d['State']['OOMKilled']
PY
cat "$target/make.log"
exit "$result"
