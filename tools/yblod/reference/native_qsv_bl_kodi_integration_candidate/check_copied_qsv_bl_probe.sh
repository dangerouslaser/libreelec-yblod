#!/bin/sh
set -eu
test "$#" = 4 || { echo 'usage: SDK_ROOT PUBLIC_ROOT V3_CANDIDATE_TARGET FRESH_OUTPUT' >&2; exit 2; }
sdk=$(realpath "$1"); public=$(realpath "$2"); candidate=$(realpath "$3"); output=$4
case "$candidate" in */target/qsv-bl-ffmpeg-isolated-v3-20261006) ;; *) exit 2 ;; esac
case "$output" in "$public"/target/qsv-bl-original-probe-compile-20261006) ;; *) exit 2 ;; esac
test ! -e "$output"
control=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
image=sha256:40b586615eae489cab72f139f659b81360da4c9e0b0787fadc5cba0119d9b29e
mkdir "$output"
id=$(docker create --name yblod-qsv-bl-original-probe-compile-20261006 \
  --memory=512m --memory-swap=512m --cpus=1 --network=none --read-only \
  --tmpfs /tmp:rw,nosuid,exec,size=32m --user 0:0 \
  -e CCACHE_DISABLE=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$sdk:/build:ro" -v "$public:/public:ro" -v "$candidate:/candidate:ro" \
  -v "$control:/control:ro" -v "$output:/lab:rw" \
  --entrypoint /bin/sh "$image" -c 'python3 /control/compile_copied_qsv_bl_probe.py')
case "$id" in ''|*[!a-f0-9]*) exit 1 ;; esac
test "${#id}" = 64
cleanup() {
 status=$?; trap - EXIT HUP INT TERM; set +e
 if test "$(docker inspect --format '{{.State.Running}}' "$id")" = true; then
   docker stop --time 10 "$id" >/dev/null 2>&1
   docker wait "$id" >/dev/null 2>&1
 fi
 docker inspect "$id" > "$output/container-after.json"
 exit "$status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker inspect "$id" > "$output/container-before.json"
python3 - "$output/container-before.json" "$id" "$image" "$sdk" "$public" "$candidate" "$control" "$output" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))[0]; h=d['HostConfig']
assert d['Id']==sys.argv[2] and d['Image']==sys.argv[3] and d['Config']['Image']==sys.argv[3]
assert h['Memory']==536870912 and h['MemorySwap']==536870912
assert h['NanoCpus']==1000000000 and h['NetworkMode']=='none' and h['ReadonlyRootfs'] and not h.get('Devices')
assert not h.get('Privileged') and not h.get('DeviceRequests')
expected=dict(zip(['/build','/public','/candidate','/control','/lab'],[(v, i==4) for i,v in enumerate(sys.argv[4:])]))
assert {m['Destination']:(m['Source'],m['RW']) for m in d['Mounts'] if m['Type']=='bind'}==expected
PY
timeout --signal=TERM --kill-after=15s 300s docker start -a "$id" > "$output/controller.log" 2>&1
docker inspect "$id" > "$output/container-after.json"
python3 - "$output/container-after.json" "$id" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))[0]
assert d['Id']==sys.argv[2] and not d['State']['Running']
assert d['State']['ExitCode']==0 and not d['State']['OOMKilled']
PY
printf 'compile_container=%s\n' "$id"
