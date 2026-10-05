#!/bin/sh
# Fixed synthetic CPU-only cohort. No display or device access.
set -eu
task_dir=$1
test "$(sha256sum "$task_dir/native_metadata_fragment_probe" | cut -d' ' -f1)" = 9f086053df1ac496db1016183ae9c856a75c418cccc18ec0ac47c18992bb651d
test "$(sha256sum /usr/lib/libavutil.so.61.1.102 | cut -d' ' -f1)" = 16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108
task_cgroup=$(awk -F: '$1=="0" {print $3}' /proc/self/cgroup)
test -n "$task_cgroup"
task_memory="/sys/fs/cgroup$task_cgroup"
test "$(cat "$task_memory/memory.max")" = 536870912
test "$(cat "$task_memory/memory.swap.max")" = 0
test "$(cat "$task_memory/memory.swap.current")" = 0
mkdir "$task_dir/cases"
for field in memory.max memory.swap.max memory.swap.current memory.peak memory.events; do
    cp "$task_memory/$field" "$task_dir/before-$field"
done
for test_case in baseline l2-2 l2-8 l2-15 l2-20 l2-21-reject boundary-119 boundary-120; do
    status=0
    "$task_dir/native_metadata_fragment_probe" "$test_case" > "$task_dir/cases/$test_case.json" 2> "$task_dir/cases/$test_case.stderr" || status=$?
    printf '%s\n' "$status" > "$task_dir/cases/$test_case.exit-status"
    if test "$test_case" = l2-21-reject; then test "$status" = 3; else test "$status" = 0; fi
done
for field in memory.max memory.swap.max memory.swap.current memory.peak memory.events; do
    cp "$task_memory/$field" "$task_dir/after-$field"
done
test "$(cat "$task_memory/memory.max")" = 536870912
test "$(cat "$task_memory/memory.swap.max")" = 0
test "$(cat "$task_memory/memory.swap.current")" = 0
before_events=$(awk '$1=="max" || $1=="oom" || $1=="oom_kill" {print}' "$task_dir/before-memory.events")
after_events=$(awk '$1=="max" || $1=="oom" || $1=="oom_kill" {print}' "$task_dir/after-memory.events")
test "$before_events" = "$after_events"
test "$(sha256sum "$task_dir/native_metadata_fragment_probe" | cut -d' ' -f1)" = 9f086053df1ac496db1016183ae9c856a75c418cccc18ec0ac47c18992bb651d
test "$(sha256sum /usr/lib/libavutil.so.61.1.102 | cut -d' ' -f1)" = 16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108
printf 'Eight synthetic fragmentation cases completed with unchanged binary/library and memory guards.\n'
