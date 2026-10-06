"""Host-only arithmetic-model and source invariants; does not execute GLSL."""
from bisect import bisect_right
from pathlib import Path
import random
import unittest
from base_mapping_stage import _mmr_terms, map_sample
from native_gpu_vectors import vector_fixtures, width_oracle, WIDTH_LIMIT

def streamed_terms(values,depth):
    y,u,v=values
    linear=1<<(20-depth);pair=1<<(20-2*depth)
    for c in values:yield c*linear,c*c*pair
    for f in (y*u*pair,y*v*pair,u*v*pair,(y*u*pair)*(v*linear)//(1<<20)):
        yield f,f*f//(1<<20)

def streamed_map(component,samples,config):
    curve=config.mappings[component]
    index=max(0,min(len(curve.segments)-1,bisect_right(curve.pivots,samples[component])-1))
    segment=curve.segments[index]
    bounded=tuple(min(m.pivots[-1],max(m.pivots[0],v)) for v,m in zip(samples,config.mappings))
    if segment.method!='mmr':return map_sample(component,samples,config)
    total=segment.constant*(1<<20)
    for term,(feature,squared) in enumerate(streamed_terms(bounded,config.bit_depth)):
        powers=(feature,squared,feature*squared//(1<<20))
        for row,coefficients in enumerate(segment.coefficients):
            total+=coefficients[term]*powers[row]
            if not -(1<<63)<=total<(1<<63):raise AssertionError('prefix overflow')
    return min(65535,max(0,total//(1<<(config.denominator+4))))

class StreamedMMRTests(unittest.TestCase):
    def test_public_corpus_model(self):
        corpus=vector_fixtures();self.assertEqual(len(corpus),32)
        rejected=0
        for v in corpus:
            if not width_oracle(v.mapping)['supported']:rejected+=1;continue
            for samples in v.triplets:
                self.assertEqual(streamed_map(v.component,samples,v.mapping),map_sample(v.component,samples,v.mapping),v.name)
        self.assertEqual(rejected,1)
    def test_features_exact_including_nested_floor(self):
        rng=random.Random(20261005)
        for depth in (8,10):
            maximum=(1<<depth)-1
            samples=[(0,0,0),(maximum,maximum,maximum),(1,maximum,maximum-1)]
            samples.extend(tuple(rng.randrange(maximum+1) for _ in range(3)) for _ in range(2048))
            for values in samples:
                rows=_mmr_terms(values,depth)
                for term,(f,s) in enumerate(streamed_terms(values,depth)):
                    self.assertEqual((f,s,f*s//(1<<20)),tuple(row[term] for row in rows))
                    self.assertTrue(0<=f<(1<<20));self.assertTrue(0<=s<(1<<20))
    def test_guard_protects_reordered_prefixes(self):
        rng=random.Random(73571)
        for _ in range(1024):
            coefficients=[rng.randrange(-10000,10001) for _ in range(21)]
            coefficients[0]=(WIDTH_LIMIT-sum(abs(v) for v in coefficients[1:]))*(-1 if rng.randrange(2) else 1)
            features=[rng.randrange(1<<20) for _ in range(21)]
            row_order=sum(a*b for a,b in zip(coefficients,features))
            total=0
            for term in range(7):
                for row in range(3):
                    i=row*7+term;total+=coefficients[i]*features[i]
                    self.assertTrue(-(1<<63)<=total<(1<<63))
            self.assertEqual(total,row_order)
    def test_source_preserves_non_mmr_and_no_feature_arrays(self):
        root=Path(__file__).resolve().parents[3]/'engine'/'experimental'
        candidate=(root/'native_gpu_streamed_mmr_probe.comp').read_text()
        original=(root/'native_gpu_probe.comp').read_text()
        self.assertNotIn('terms[',candidate);self.assertNotIn('codes[',candidate)
        self.assertEqual(candidate.split('    int64_t mapped=',1)[1],original.split('    int64_t mapped=',1)[1])
        self.assertIn('floor_power_two(feature*squared,20)',candidate)
        self.assertIn('floor_power_two(feature*feature,20)',candidate)

if __name__=='__main__':unittest.main()
