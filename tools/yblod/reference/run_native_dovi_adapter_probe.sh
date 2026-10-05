#!/bin/sh
# Fixed actual-allocator synthetic cohort; no decoder/GPU/display interaction.
set -eu
task_dir=$1
test "$(sha256sum "$task_dir/native_dovi_adapter_probe" | cut -d' ' -f1)" = 4a0090f47d336420f126a6beb122c88918622b9358d1e1fa7557bbd9da8544b9
test "$(sha256sum "$task_dir/native_dovi_adapter_probe_ubsan" | cut -d' ' -f1)" = 4cbb9bbdcbf5b8475e7208f05809ae1f278f109584de116d3993181dd13d7974
test "$(sha256sum "$task_dir/libubsan.so.1" | cut -d' ' -f1)" = 429866ada58bdd88bd5e50e4d20ddc35c6e4d3e96101b1886da9e94deb4ae323
test "$(sha256sum /usr/lib/libavutil.so.61.1.102 | cut -d' ' -f1)" = 16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108
task_cgroup=$(awk -F: '$1=="0" {print $3}' /proc/self/cgroup)
test -n "$task_cgroup"
task_memory="/sys/fs/cgroup$task_cgroup"
test "$(cat "$task_memory/memory.max")" = 536870912
test "$(cat "$task_memory/memory.swap.max")" = 0
test "$(cat "$task_memory/memory.swap.current")" = 0
mkdir "$task_dir/cases" "$task_dir/ubsan-cases"
for field in memory.max memory.swap.max memory.swap.current memory.peak memory.events; do
    cp "$task_memory/$field" "$task_dir/before-$field"
done
sha256sum /usr/lib/libstdc++.so.6 /usr/lib/libgcc_s.so.1 > "$task_dir/before-runtime.sha256"
for test_case in baseline negative-coefficient cumulative-pivots mmr1 mmr2 mmr3 \
    poisoned-inactive disabled-poisoned-nlq disabled-denominator13 depth8 spatial-flags empty-ext-at-end \
    float-coefficients explicit-chroma-filter invalid-chroma-flag unknown-header \
    unsupported-depth multiple-partitions unknown-method mmr-luma bad-nlq-method \
    wrong-nlq-pivots late-offset-overflow late-coefficient-overflow duplicate-pivots \
    truncated offset-wrap overlap-regions overlap-prefix overlap-ext \
    bad-ext-stride negative-ext-count output-alias address-wrap \
    null-input null-output misaligned-input misaligned-output wrapping-output oversized-bytes; do
    "$task_dir/native_dovi_adapter_probe" "$test_case" > "$task_dir/cases/$test_case.json" 2> "$task_dir/cases/$test_case.stderr"
    printf '0\n' > "$task_dir/cases/$test_case.exit-status"
    LD_LIBRARY_PATH="$task_dir" "$task_dir/native_dovi_adapter_probe_ubsan" "$test_case" > "$task_dir/ubsan-cases/$test_case.json" 2> "$task_dir/ubsan-cases/$test_case.stderr"
    printf '0\n' > "$task_dir/ubsan-cases/$test_case.exit-status"
    test ! -s "$task_dir/cases/$test_case.stderr"
    test ! -s "$task_dir/ubsan-cases/$test_case.stderr"
    test "$(sha256sum "$task_dir/cases/$test_case.json" | cut -d' ' -f1)" = "$(sha256sum "$task_dir/ubsan-cases/$test_case.json" | cut -d' ' -f1)"
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
test "$(sha256sum "$task_dir/native_dovi_adapter_probe" | cut -d' ' -f1)" = 4a0090f47d336420f126a6beb122c88918622b9358d1e1fa7557bbd9da8544b9
test "$(sha256sum "$task_dir/native_dovi_adapter_probe_ubsan" | cut -d' ' -f1)" = 4cbb9bbdcbf5b8475e7208f05809ae1f278f109584de116d3993181dd13d7974
test "$(sha256sum "$task_dir/libubsan.so.1" | cut -d' ' -f1)" = 429866ada58bdd88bd5e50e4d20ddc35c6e4d3e96101b1886da9e94deb4ae323
test "$(sha256sum /usr/lib/libavutil.so.61.1.102 | cut -d' ' -f1)" = 16e16a2ab0f89a48c7e487d365e84f1c005f119fa8754c146daaeff40883c108
sha256sum /usr/lib/libstdc++.so.6 /usr/lib/libgcc_s.so.1 > "$task_dir/after-runtime.sha256"
test "$(sha256sum "$task_dir/before-runtime.sha256" | cut -d' ' -f1)" = "$(sha256sum "$task_dir/after-runtime.sha256" | cut -d' ' -f1)"
printf 'Forty normal and forty UBSan synthetic cases completed with matching output digests, unchanged artifacts and memory guards.\n'
