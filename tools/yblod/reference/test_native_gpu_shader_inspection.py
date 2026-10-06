import unittest
from native_gpu_shader_inspection import parse

HEADER='Native code for unnamed compute shader GLSL2 (src_hash 0x00000000cdb9fc45) (blake3 '+('a'*64)+')\n'
STAT='SIMD8 shader: 1582 instructions. 3 loops. 20424 cycles. 42:14 spills:fills, 23 sends, scheduled with mode non-lifo. Promoted 2 constants. GRF registers: 128. Non-SSA regs (after NIR): 36. Compacted 27584 to 23152 bytes (16%)\n'

class InspectionTests(unittest.TestCase):
    def test_static_only(self):
        r=parse((HEADER+STAT).encode())
        self.assertEqual(r['statistics']['spill_count'],42)
        self.assertEqual(r['statistics']['fill_count'],14)
        self.assertEqual(r['statistics']['compiler_estimated_cycles'],20424)
        self.assertFalse(r['statistics_are_measured_runtime'])
        self.assertFalse(r['spill_fill_counts_are_allocator_only'])
    def test_ambiguous_or_missing_rejected(self):
        for s in ('',HEADER,STAT,HEADER+STAT+HEADER+STAT,STAT+HEADER):
            with self.subTest(s=s),self.assertRaises(ValueError):parse(s.encode())
    def test_invalid_bounds_rejected(self):
        for data in (b'\xff',b'x'*(8*1024*1024+1),(HEADER+STAT.replace('128.','0.')).encode(),(HEADER+STAT.replace('1582',str(2**64))).encode()):
            with self.assertRaises((ValueError,UnicodeError)):parse(data)
    def test_failures_recorded_not_inferred(self):
        r=parse(('SIMD16 CS compile failed: Failure to register allocate.\n'+HEADER+STAT+'SIMD32 shader inefficient\n').encode())
        self.assertTrue(r['simd16_register_allocation_failed'])
        self.assertTrue(r['simd32_inefficient'])

if __name__=='__main__':unittest.main()
