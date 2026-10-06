"""Strict parser for one synthetic Mesa compiler inspection, not GPU timings."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HEADER = re.compile(r'^Native code for .* compute shader .* \(src_hash 0x[0-9a-f]+\) \(blake3 ([0-9a-f]{64})\)$', re.M)
STATS = re.compile(r'^SIMD(8|16|32) shader: ([0-9]+) instructions\. ([0-9]+) loops\. ([0-9]+) cycles\. ([0-9]+):([0-9]+) spills:fills, ([0-9]+) sends, .* GRF registers: ([0-9]+)\. Non-SSA regs \(after NIR\): ([0-9]+)\. Compacted ([0-9]+) to ([0-9]+) bytes \(([0-9]+)%\)$', re.M)

def parse(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= 8*1024*1024:
        raise ValueError('bounded compiler log bytes required')
    text = data.decode('utf-8', errors='strict')
    headers=list(HEADER.finditer(text)); stats=list(STATS.finditer(text))
    if len(headers)!=1 or len(stats)!=1 or headers[0].end()>stats[0].start():
        raise ValueError('one unambiguous native compute shader and statistics required')
    keys=('simd_width','instruction_count','loop_count','compiler_estimated_cycles','spill_count','fill_count','send_count','grf_registers','non_ssa_registers','uncompacted_code_bytes','compacted_code_bytes','compaction_percent')
    values=[int(v) for v in stats[0].groups()]
    if any(v>2**63-1 for v in values) or values[1]==0 or values[7]==0:
        raise ValueError('invalid compiler statistics')
    return dict(schema='yblod.synthetic-shader-compiler-stats.v1',compiler_log_sha256=hashlib.sha256(data).hexdigest(),shader_binary_blake3=headers[0].group(1),statistics=dict(zip(keys,values)),simd16_register_allocation_failed='SIMD16 CS compile failed: Failure to register allocate.' in text,simd32_inefficient='SIMD32 shader inefficient' in text,statistics_are_measured_runtime=False,spill_fill_counts_are_allocator_only=False,interpretation='Compiler static statistics; not GPU elapsed time, playback FPS, or a production shader comparison. Spill/fill counters include source scratch accesses and register allocator spills/fills; neither their origins nor dynamic frequency are apportioned. NIR scratch is not reported as spill allocation.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler_log',type=Path)
    args=parser.parse_args()
    with args.compiler_log.open('rb') as stream:data=stream.read(8*1024*1024+1)
    print(json.dumps(parse(data),indent=2))

if __name__=='__main__':main()
