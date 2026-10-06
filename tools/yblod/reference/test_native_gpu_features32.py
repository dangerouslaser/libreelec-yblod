"""Exact bounded feature math proof; no compiler, GPU or playback operations."""
from pathlib import Path
import hashlib,itertools,json,random,unittest
ROOT=Path(__file__).resolve().parents[3] if Path(__file__).resolve().parent.name == 'reference' else Path(__file__).resolve().parent
ENGINE=ROOT/'engine/experimental' if (ROOT/'engine/experimental').is_dir() else ROOT
CANDIDATE=ENGINE/'native_gpu_composer_backend_features32.comp'
ORIGINAL=ENGINE/'native_gpu_composer_backend.comp'
BACKEND=ROOT/'engine/experimental/native_gpu_composer_backend.c' if (ROOT/'engine/experimental').is_dir() else ROOT/'features32_baseline_backend.c'
COMPOSER=ROOT/'engine/src/native_composer.c' if (ROOT/'engine/src').is_dir() else ROOT/'features32_baseline_composer.c'
MAX=1023
def original_triple(y,cb,cr):return ((y*cb)*(cr<<10))//(1<<20)
def candidate_triple(y,cb,cr):return (y*cb*cr)>>10
class Features32CandidateTests(unittest.TestCase):
    def test_saved_abba_exact_scope_and_shader_pins(self):
        directory=Path(__file__).resolve().parent
        path=(directory/'results/native-features32-abba-20261006.json'
              if directory.name=='reference' else directory/'NATIVE_FEATURES32_ABBA_RESULTS.json')
        report=json.loads(path.read_text())
        self.assertEqual(report['schema'],'yblod.native-gpu-features32-abba.v1')
        self.assertFalse(report['production_adopted'])
        self.assertEqual(report['failed_attempts'],0)
        self.assertEqual(report['retries'],0)
        self.assertEqual([r['id'] for r in report['runs']],['A1','B1','B2','A2'])
        for source,key in ((ORIGINAL,'baseline_shader_sha256'),(CANDIDATE,'candidate_shader_sha256')):
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),report[key])
        gates=report['each_run']
        self.assertEqual(gates['cpu_stage_values'],49766400)
        self.assertEqual(gates['gpu_exact_reconstructed_values'],12441600)
        for key in ('full_frame_exact','cleanup_succeeded','pins_and_kodi_identity_unchanged','memory_events_all_zero'):
            self.assertTrue(gates[key])
        for key in ('swap_bytes','nr_throttled_delta','throttled_usec_delta'):
            self.assertEqual(gates[key],0)
        self.assertEqual(gates['memory_limit_bytes'],536870912)
        self.assertEqual(gates['cpu_max'],'100000 100000')
        for r in report['runs']:
            self.assertEqual(len(r['wall_ns']),3)
            self.assertEqual(len(r['cpu_ns']),3)
            self.assertTrue(all(0<n<5000000000 for n in r['wall_ns']+r['cpu_ns']))
            self.assertLess(r['memory_peak_snapshot_bytes'],536870912)
        for variant,key in (('A','baseline'),('B','candidate')):
            values=sorted(n for r in report['runs'] if r['id'][0]==variant for n in r['wall_ns'])
            self.assertEqual((values[2]+values[3])/2,report['pooled_median_wall_ns'][key])
        self.assertIn('no established playback benefit',report['conclusion'])
        medians=report['pooled_median_wall_ns']
        self.assertEqual(medians,{'baseline':16876356,'candidate':16122635.5})
        expected_reduction=100*(1-medians['candidate']/medians['baseline'])
        self.assertAlmostEqual(report['pooled_median_wall_reduction_percent'],expected_reduction,places=12)
        self.assertIn('4.47%',report['conclusion'])
        for marker in ('/storage/','/home/','/private/','instructions.bin','scaled1.p010'):
            self.assertNotIn(marker,path.read_text())
    def test_exact_bounds_and_all_single_codes(self):
        self.assertEqual(MAX*MAX,1046529)
        self.assertEqual(MAX*MAX*MAX,1070599167)
        self.assertLess(MAX<<10,1<<20)
        self.assertLess(MAX*MAX,1<<20)
        self.assertLess(MAX*MAX*MAX,1<<30)
        self.assertLess(MAX*MAX*MAX*(1<<10),1<<40)
        for code in range(1024):
            self.assertEqual(code<<10,code*(1<<(20-10)))
            self.assertEqual(code*code,code*code*(1<<(20-2*10)))
    def test_exhaustive_1048576_pairs_without_narrowing_products_of_features(self):
        checked=0
        for a in range(1024):
            for b in range(1024):
                product=a*b
                if product!=(a*(1<<10)*b*(1<<10))//(1<<20) or product>1046529:
                    self.fail(f'pair mismatch {a},{b}')
                checked+=1
        self.assertEqual(checked,1048576)
    def test_triple_boundary_and_seeded_cases_preserve_floor(self):
        values=(0,1,2,511,512,513,1022,1023)
        cases=list(itertools.product(values,repeat=3))
        rng=random.Random(0x5932)
        cases.extend(tuple(rng.randrange(1024) for _ in range(3)) for _ in range(20000))
        for y,cb,cr in cases:
            self.assertEqual(original_triple(y,cb,cr),candidate_triple(y,cb,cr))
            self.assertLessEqual(y*cb*cr,1070599167)
        self.assertEqual(len(cases),20512)
    def test_actual_admission_and_integer_word_guards_support_bounds(self):
        backend=BACKEND.read_text();composer=COMPOSER.read_text();shader=CANDIDATE.read_text()
        self.assertIn('p->mapping.bit_depth==10',backend)
        self.assertIn('pivot < 0 || pivot > native_max',composer)
        self.assertIn('const int32_t native_max = (1 << config->bit_depth) - 1',composer)
        self.assertIn('if(((y|enhancement)&63u)!=0u)',shader)
        self.assertIn('if(((cb|cr|enhancement)&63u)!=0u || y>1023u)',shader)
        self.assertIn('if (depth==10)',shader)
        self.assertIn('int64_t((iy*icb*icr)>>10u)',shader)
    def test_coefficient_accumulator_floors_fetch_and_fallback_unchanged(self):
        original=ORIGINAL.read_text();candidate=CANDIDATE.read_text()
        self.assertEqual(original.split('void main()',1)[0],candidate.split('void main()',1)[0])
        self.assertEqual(original.split('int64_t mapped=',1)[1],candidate.split('int64_t mapped=',1)[1])
        self.assertIn('int64_t total=int64_t(0)',candidate)
        self.assertIn('floor_power_two(feature*feature,20)',candidate)
        self.assertIn('floor_power_two(feature*squared,20)',candidate)
        self.assertIn('m[offset+3+term]*feature',candidate)
        fallback=candidate.split('// Preserve generic metadata-depth behavior as the original path.',1)[1].split('\n        }',1)[0].strip()
        old=original.split('total=m[offset+2]*(int64_t(1) << 20);',1)[1].split('\n    }',1)[0].strip()
        self.assertEqual(fallback,old)
if __name__=='__main__':unittest.main()
