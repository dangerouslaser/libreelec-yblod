#!/bin/sh
# Private execution wrapper: run only inside a fresh 512MiB/no-swap scope.
set -eu
base=$1
shift
case "$base" in /*) ;; *) exit 2;; esac
cg=$(sed -n 's/^0:://p' /proc/self/cgroup)
test -n "$cg"
cgdir=/sys/fs/cgroup$cg
test "$(cat "$cgdir/memory.max")" = 536870912
test "$(cat "$cgdir/memory.swap.max")" = 0
snapshot() {
    for item in memory.current memory.peak memory.max memory.swap.current memory.swap.max memory.events; do
        printf '%s\n' "$item"
        cat "$cgdir/$item"
    done
}
snapshot > "$base.memory-before.txt"
set +e
"$@" > "$base.stdout.json" 2> "$base.stderr.txt"
status=$?
set -e
snapshot > "$base.memory-after.txt"
printf '%s\n' "$status" > "$base.exit-status.txt"
exit "$status"
