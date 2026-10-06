# Synthetic compiled shader inspection

## Reproduction safety

The collector does not enforce its own memory/swap limits. Its live invocation
must run inside an external 512 MiB/no-job-swap scope; never run it directly
without those limits. CPU validation and the child GPU inspection each have
a 30-second timeout. Use a fresh output directory and normal Python execution
(do not disable assertions). The collector expects the previously staged,
reviewed synthetic v2 source/binary directory named in its source.

```sh
systemd-run --scope -p MemoryMax=512M -p MemorySwapMax=0 \
  python3 native_gpu_shader_inspection_collect.py NEW-SYNTHETIC-INSPECTION-DIRECTORY
```

Do not aim these debug settings at Kodi or a movie-frame runner. They change
the diagnostic compilation workload and must remain separate from timing runs.

The current generic integer diagnostic compiles on the VM as SIMD8 with 1,582
instructions, 128 GRF registers and compiler-reported 42 spills / 14 fills.
SIMD16 register allocation failed; SIMD32 was reported inefficient. These are
real compiler diagnostics, not inferred from playback timings. The spill/fill
counters include both source-level scratch accesses and register allocator
spills/fills; they are not 42 proven allocator spills or dynamic transfer counts.
They show an optimization target but do not establish how much runtime any particular
operation costs or compare against Kodi's production float shader.

The public synthetic MMR3 fixture has 125 positions. Its independent Python
CPU gate passed before the single GPU dispatch; all four native stage mismatch
counts were zero. The renderer reported TGL GT2 / OpenGL 4.6 / Mesa 26.2.4.
Memory peaked at 60,960,768 bytes under 512 MiB, job swap was zero, memory events
were all zero and Kodi PID/start identity remained unchanged.

Results and raw evidence:

- [Collection report](results/native-gpu-shader-inspection-20261005a.json)
- [Compiler statistics](results/native-gpu-shader-inspection-stats-20261005a.json)
- [Raw compiler log](results/native-gpu-shader-inspection-20261005a.log)
- [Exactness report](results/native-gpu-shader-inspection-exact-20261005a.json)

The collector used only reviewed public source and synthetic metadata. Child-only
`INTEL_DEBUG=cs,ann,perf`, `INTEL_SHADER_BIN_DUMP_PATH` and
`MESA_SHADER_CACHE_DISABLE=true` forced a fresh diagnostic compilation. No Kodi
environment, clocks, shared caches or SIMD policies changed. Mapped library pins
record loaded candidates, not proof that every candidate was selected. The
renderer and verified render-node binding establish the diagnostic's Intel route.

The assembly header associates the statistics with binary blake3
`8cbd13a1868e72dae4ad444d532387bfc9d36a050a174012d019c122b1a93939`.
The reviewed shader SHA256 is
`a708d8c27ff75effdf166fbfe3f5cae88ffaec34a784f234441ed1cc96d166bb`.
Metadata comes from SSBO inputs rather than compile-time movie constants; this
single MMR3 fixture does not specialize away the generic shader's other paths.

The reported 20,424 cycles are a compiler estimate, not a device measurement.
The audited Mesa `brw_from_nir.cpp:5811–5814` increments the same spill/fill
counters for source scratch loads/stores that `brw_reg_allocate.cpp:891,974`
uses for allocator spill/fill instructions. `brw_to_binary.cpp:2178–2195`
prints these static counters and its `perf.latency` estimate. The raw output
does not separate the two scratch-access origins.
NIR `scratch: 168` is not reported here as runtime spill allocation. Annotated
logs and static instruction counts are not a proof that int64 lowering alone
caused previous wall times. Driver-internal binary dumps remain private diagnostic
artifacts; public raw log contains reviewed shader IR/assembly only, no film data.

Next: inspect streamed MMR feature accumulation / shorter temporary lifetimes,
and compare compiler statistics with an exactness-gated candidate. Preserve
individual floors and signed accumulation bounds; do not replace arithmetic with
float merely to remove spills. Actual VA-surface integration is a separate gate.

Mesa documents the diagnostic controls in its
[official environment-variable reference](https://docs.mesa3d.org/envvars.html).
`native_gpu_shader_inspection.py` parses one unambiguous compiler statistics block;
it rejects missing or multiple native shader blocks rather than reporting zero.
