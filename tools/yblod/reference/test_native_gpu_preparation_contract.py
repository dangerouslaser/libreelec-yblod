"""Source contract checks only; no claim of GLSL execution or pixel equality."""
from pathlib import Path
import unittest

ENGINE=Path(__file__).resolve().parents[3]/'engine/experimental'

class PreparationContracts(unittest.TestCase):
    def test_guide_and_explicit_phase_contract(self):
        source=(ENGINE/'native_gpu_preparation_probe.comp').read_text()
        for text in ('left.x+2*center.x+right.x+2','(first+second+1)>>1',
                     '(3*b+c+2)>>2','-9*a+111*b+29*c-3*d+64',
                     'float(guide)/65535.0','vec2(result<<6)/65535.0'):
            self.assertIn(text,source)
        self.assertLess(source.index('operation>2u'),source.index('greaterThanEqual(pixel,output_size)'))
        self.assertIn('((words.x|words.y)&63u)!=0u',source)
        self.assertNotIn('texture(native_plane',source)

    def test_separate_scaler_passes_and_native_overshoot_rejection(self):
        source=(ENGINE/'native_gpu_el_scaling_probe.comp').read_text()
        for text in ('int[4](-3,29,111,-9)','int[4](-9,111,29,-3)',
                     'int[8](22,94,-524,2456,2456,-524,94,22)',
                     'sum=rounded(sum,7)','sum=rounded(sum,12)',
                     'greaterThan(sum,ivec2(1023))','atomicOr(failure,4u)'):
            self.assertIn(text,source)
        self.assertIn('ivec2(65535)',source)
        self.assertNotIn('sum=clamp(sum,ivec2(0),ivec2(1023))',source)

    def test_signed_accumulation_bounds(self):
        phase=sum(map(abs,(-9,111,29,-3)))*1023+64
        horizontal=sum(map(abs,(22,94,-524,2456,2456,-524,94,22)))*65535+2048
        self.assertLess(phase,2**31)
        self.assertLess(horizontal,2**31)

if __name__=='__main__':unittest.main()
