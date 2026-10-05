from fractions import Fraction
import itertools
import unittest

import composition_stage as stage
from nlq_stage import NLQConfig
import reference


class CompositionStageTests(unittest.TestCase):
    def test_all_mapped_codes_base_only_both_depths(self):
        for depth in (10,12):
            for mapped,actual in enumerate(stage.iter_base_only(range(65536),depth)):
                self.assertEqual(actual,reference.reconstruct(mapped,0,depth))

    def test_integer_el_connected_to_independent_reference(self):
        count=0
        for el_depth in (8,10):
            center=1<<(el_depth-1)
            for denominator,slope,threshold,maximum in ((el_depth+5,3,5,1000),(23,2048,0,1025),
                                                      (32,(2<<32)-1,(2<<32)-1,(2<<32)-1)):
                config=NLQConfig(el_depth,denominator,center,slope,threshold,maximum)
                parameters=dict(offset=center,slope=slope,threshold=threshold,maximum=maximum)
                for depth in (10,12):
                    for mapped in (0,7,8,31,32,32768,65503,65504,65535):
                        for sample in range(1<<el_depth):
                            residual=reference.inverse_el(sample,parameters,el_depth,denominator)
                            self.assertEqual(stage.compose(mapped,sample,config,depth),reference.reconstruct(mapped,residual,depth))
                            count+=1
        self.assertEqual(count,69120)

    def test_half_round_and_bounds_without_residual_storage_clamp(self):
        self.assertEqual([stage.compose_residual(0,v,12) for v in (7,8,9,23,24)], [0,1,1,1,2])
        self.assertEqual([stage.compose_residual(0,v,10) for v in (31,32,33,95,96)], [0,1,1,1,2])
        for depth in (10,12):
            for mapped in (0,1,32768,65535):
                for residual in (-10**50,-131072,-65536,-17,-8,-1,0,1,8,17,65536,131071,10**50):
                    self.assertEqual(stage.compose_residual(mapped,residual,depth),reference.reconstruct(mapped,residual,depth))
        self.assertEqual(stage.compose_residual(65535,-65535,12),0)
        self.assertEqual(stage.compose_residual(65535,-65536,12),0)
        self.assertEqual(stage.compose_residual(0,65535,12),4095)

    def test_independent_literal_signed_half_and_upper_edge_vectors(self):
        cases={12:((0,7,0),(0,8,1),(16,-8,1),(16,-9,0),(160,-80,5),
                   (65520,-8,4095),(65520,-9,4094),(65535,-24,4094),(65535,80,4095)),
               10:((0,31,0),(0,32,1),(64,-32,1),(64,-33,0),(640,-320,5),
                   (65472,-32,1023),(65472,-33,1022),(65535,-96,1022))}
        for depth,values in cases.items():
            for mapped,residual,expected in values:
                self.assertEqual(stage.compose_residual(mapped,residual,depth),expected)

    def test_strict_validation_no_fallback(self):
        config=NLQConfig(10,23,512,2048,0,1024)
        for mapped in (True,0.0,Fraction(0),-1,65536):
            with self.assertRaises(ValueError): stage.compose_residual(mapped,0,12)
        for residual in (True,0.0,Fraction(0),None):
            with self.assertRaises(ValueError): stage.compose_residual(0,residual,12)
        for depth in (True,12.0,8,16,None):
            with self.assertRaises(ValueError): stage.compose_residual(0,0,depth)
            with self.assertRaises(ValueError): stage.iter_base_only([],depth)
            with self.assertRaises(ValueError): stage.iter_composed([],[],config,depth)
        for sample in (None,True,512.0,-1,1024):
            with self.assertRaises(ValueError): stage.compose(32768,sample,config,12)
        with self.assertRaises(ValueError): stage.iter_composed([],[],None,12)
        with self.assertRaises(ValueError): stage.compose(32768,512,None,12)

    def test_stream_lengths_both_directions_fail_when_exhausted(self):
        config=NLQConfig(10,23,512,2048,0,1024)
        self.assertEqual(list(stage.iter_composed([],[],config,12)),[])
        for mapped,el in (([32768,32768],[512]),([32768],[512,512]),([],[512]),([0],[])):
            with self.assertRaisesRegex(ValueError,"different lengths"):
                list(stage.iter_composed(iter(mapped),iter(el),config,12))
        partial=stage.iter_composed([32768,32768],[512],config,12)
        self.assertEqual(next(partial),2048)
        with self.assertRaises(ValueError): next(partial)

    def test_laziness_and_explicit_base_only(self):
        config=NLQConfig(10,23,512,2048,0,1024)
        consumed=[]
        def mapped():
            for value in (32768,65535):
                consumed.append(value)
                yield value
        values=stage.iter_composed(mapped(),iter((512,512)),config,12)
        self.assertEqual(consumed,[])
        self.assertEqual(next(values),2048)
        self.assertEqual(consumed,[32768])
        self.assertEqual(next(values),4095)
        infinite=stage.iter_composed(itertools.repeat(32768),itertools.repeat(512),config,12)
        self.assertEqual(list(itertools.islice(infinite,100)),[2048]*100)
        self.assertEqual(list(stage.iter_base_only((0,8,65535),12)),[0,1,4095])


if __name__ == "__main__": unittest.main()
