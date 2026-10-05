from dataclasses import FrozenInstanceError
from fractions import Fraction
import itertools
import unittest

import nlq_stage as stage
import reference


class NLQStageTests(unittest.TestCase):
    def test_exhaustive_domains_against_independent_reference(self):
        cases = []
        for depth in (8,10):
            for denominator in (depth+5,23,32):
                bound=(2<<denominator)-1
                for offset in (0,1,(1<<depth)//2,(1<<depth)-1):
                    for slope,threshold,maximum in ((0,0,0),(0,7,5),(1,0,1),(2048,0,1025),
                                                    (3,11,17),(bound,bound,bound),(bound,0,1)):
                        cases.append(stage.NLQConfig(depth,denominator,offset,slope,threshold,maximum))
        count=0
        for config in cases:
            parameters={name:getattr(config,name) for name in ("offset","slope","threshold","maximum")}
            for sample in range(1<<config.bit_depth):
                expected=reference.inverse_el(sample,parameters,config.bit_depth,config.denominator)
                self.assertEqual(stage.correction(sample,config),expected)
                count+=1
        self.assertEqual(count,107520)

    def test_neutral_and_clip_before_signed_floor_vectors(self):
        config=stage.NLQConfig(10,23,512,2048,0,1025)
        self.assertEqual([stage.correction(v,config) for v in (510,511,512,513,514)],[-9,-8,0,8,8])
        config=stage.NLQConfig(8,13,128,0,5,2)
        self.assertEqual([stage.correction(v,config) for v in (0,127,128,129,255)],[-16,-16,0,16,16])
        config=stage.NLQConfig(10,32,512,1,0,(2<<32)-1)
        self.assertEqual(stage.correction(511,config),-1)
        self.assertEqual(stage.correction(513,config),0)

    def test_independent_literal_depth_threshold_and_shift_vectors(self):
        vectors=((stage.NLQConfig(8,13,128,3,1,5),(128,129,130,127,126),(0,20,40,-20,-40)),
                 (stage.NLQConfig(8,14,128,3,1,5),(128,129,130,127,126),(0,10,20,-10,-20)),
                 (stage.NLQConfig(8,13,128,3,5,1000),(128,129,127,130,126),(0,52,-52,76,-76)),
                 (stage.NLQConfig(10,15,512,3,5,1000),(512,513,511,514,510),(0,13,-13,19,-19)),
                 (stage.NLQConfig(10,16,512,3,0,100),(513,511,514,510),(1,-2,4,-5)),
                 (stage.NLQConfig(8,16,128,3,0,100),(129,127,130,126),(1,-2,4,-5)))
        for config,samples,expected in vectors:
            self.assertEqual(tuple(stage.iter_corrections(samples,config)),expected)
        for depth in (8,10):
            config=stage.NLQConfig(depth,depth+5,1,17,23,0)
            self.assertEqual(list(stage.iter_corrections(range(1<<depth),config)),[0]*(1<<depth))
            center=1<<(depth-1)
            config=stage.NLQConfig(depth,32,center,(2<<32)-1,0,(2<<32)-1)
            self.assertEqual(tuple(stage.iter_corrections((center,center+1,center-1,center+2,center-2),config)),
                             (0,65535,-65536,131071,-131072))

    def test_config_immutable_and_mapping_copied(self):
        parameters=dict(offset=512,slope=2048,threshold=0,maximum=1024)
        config=stage.NLQConfig.from_mapping(parameters,bit_depth=10,denominator=23)
        parameters["maximum"]=0
        self.assertEqual(config.maximum,1024)
        with self.assertRaises(FrozenInstanceError): config.maximum=0
        self.assertEqual(hash(config),hash(stage.NLQConfig(10,23,512,2048,0,1024)))

    def test_metadata_and_sample_reject_inexact_invalid_values(self):
        good=dict(bit_depth=10,denominator=23,offset=512,slope=2048,threshold=0,maximum=1024)
        invalid={"bit_depth":(True,10.0,9),"denominator":(True,23.0,14,33),
                 "offset":(True,512.0,-1,1024),"slope":(True,1.0,-1,1<<24),
                 "threshold":(True,1.0,-1,1<<24),"maximum":(True,1.0,-1,1<<24)}
        for field,values in invalid.items():
            for value in values:
                with self.assertRaises(ValueError): stage.NLQConfig(**dict(good,**{field:value}))
        for parameters in (None,{},dict(offset=512,slope=1,threshold=0,maximum=1,other=0)):
            with self.assertRaises(ValueError): stage.NLQConfig.from_mapping(parameters,bit_depth=10,denominator=23)
        config=stage.NLQConfig(**good)
        for sample in (True,512.0,Fraction(512),-1,1024,"512"):
            with self.assertRaises(ValueError): stage.correction(sample,config)
        for invalid_config in (None,good):
            with self.assertRaises(ValueError): stage.correction(512,invalid_config)

    def test_iterators_are_lazy_bounded_and_validate_on_consumption(self):
        config=stage.NLQConfig(10,23,512,2048,0,1024)
        consumed=[]
        def samples():
            for v in (511,512,513,1024):
                consumed.append(v)
                yield v
        values=stage.iter_corrections(samples(),config)
        self.assertEqual(consumed,[])
        self.assertEqual(list(itertools.islice(values,3)),[-8,0,8])
        self.assertEqual(consumed,[511,512,513])
        with self.assertRaises(ValueError): next(values)
        rows=stage.iter_rows(iter((iter((511,512)),iter((513,)))),config)
        self.assertEqual(list(next(rows)),[-8,0])
        self.assertEqual(list(next(rows)),[8])
        with self.assertRaises(StopIteration): next(rows)
        infinite=stage.iter_corrections(itertools.repeat(512),config)
        self.assertEqual(list(itertools.islice(infinite,100)),[0]*100)


if __name__ == "__main__": unittest.main()
