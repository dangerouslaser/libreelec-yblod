import copy
from dataclasses import FrozenInstanceError
from fractions import Fraction
import itertools
import unittest

import base_mapping_stage as stage
import reference


def poly(pivots,coefficients):
    return dict(pivots=pivots,segments=[dict(method="polynomial",coefficients=coefficients) for _ in pivots[1:]])


def mmr(pivots,rows,constant=0):
    return dict(pivots=pivots,segments=[dict(method="mmr",coefficients=rows,constant=constant) for _ in pivots[1:]])


class BaseMappingTests(unittest.TestCase):
    def test_exhaustive_polynomial_native_domains_against_reference(self):
        count=0
        for depth in (8,10):
            last=(1<<depth)-1
            for denominator in (13,23,32):
                unit=1<<denominator
                for coefficients in ((0,unit),(128,0),(0,0,unit),(-unit,2*unit,-unit),
                                     (unit,0),((64<<denominator)-1,-(64<<denominator))):
                    source=[poly([1,last//2,last-1],list(coefficients)) for _ in range(3)]
                    config=stage.BaseMappingConfig.from_mappings(source,bit_depth=depth,denominator=denominator)
                    for sample in range(last+1):
                        samples=[sample,sample,sample]
                        for component in range(3):
                            self.assertEqual(stage.map_sample(component,samples,config),
                                             reference.map_sample(component,samples,source,depth,denominator))
                            count+=1
        self.assertEqual(count,69120)

    def test_varied_mmr_orders_all_native_guide_codes_against_reference(self):
        count=0
        for depth in (8,10):
            last=(1<<depth)-1
            for denominator in (13,23,32):
                unit=1<<denominator
                for order in (1,2,3):
                    rows=[[unit//(i+1)*(1 if j%2 else -1) for j in range(7)] for i in range(order)]
                    source=[poly([3,last-3],[0,unit]),mmr([11,last-7],rows,unit//2),mmr([17,last-13],rows,-unit//3)]
                    config=stage.BaseMappingConfig.from_mappings(source,bit_depth=depth,denominator=denominator)
                    for y in range(last+1):
                        samples=[y,(y*17+3)%(last+1),(y*31+7)%(last+1)]
                        for component in (1,2):
                            self.assertEqual(stage.map_sample(component,samples,config),
                                             reference.map_sample(component,samples,source,depth,denominator))
                            count+=1
        self.assertEqual(count,23040)

    def test_independent_literals_and_right_owned_pivots(self):
        unit=1<<23
        identity=poly([0,1023],[0,unit])
        cases=((poly([64,960],[0,unit]),0,4096),(poly([64,960],[0,unit]),1023,61440),
               (poly([0,1023],[127,0]),512,0),(poly([0,1023],[128,0]),512,1),
               (poly([0,1023],[-1,0]),512,0),(poly([0,1023],[unit,0]),512,65535),
               (poly([0,1023],[0,0,unit]),512,16384),(poly([0,1023],[0,0,unit]),1023,65408))
        for mapping,sample,expected in cases:
            config=stage.BaseMappingConfig(10,23,[mapping,identity,identity])
            self.assertEqual(stage.map_sample(0,[sample,0,0],config),expected)
        piece=dict(pivots=[0,512,1023],segments=[dict(method="polynomial",coefficients=[128,0]),dict(method="polynomial",coefficients=[256,0])])
        config=stage.BaseMappingConfig(10,23,[piece,identity,identity])
        self.assertEqual([stage.map_sample(0,[v,0,0],config) for v in (511,512,1023)],[1,2,2])
        cross=mmr([0,1023],[[0,0,0,unit,0,0,0]])
        config=stage.BaseMappingConfig(10,23,[identity,cross,identity])
        self.assertEqual(stage.map_sample(1,[33,17,0],config),35)
        # All input pivots clamp independently; Yguide andCb bounds differ.
        config=stage.BaseMappingConfig(10,23,[poly([64,960],[0,unit]),mmr([16,900],[[unit,0,0,0,0,0,0]]),identity])
        self.assertEqual(stage.map_sample(1,[0,17,0],config),4096)

    def test_mmr_sum_before_clip_and_intermediate_product_floors(self):
        unit=1<<23
        identity=poly([0,1023],[0,unit])
        # Positive constant andnegativeY cancel before finalbound.
        config=stage.BaseMappingConfig(10,23,[identity,mmr([0,1023],[[-unit,0,0,0,0,0,0]],unit//2),identity])
        self.assertEqual(stage.map_sample(1,[512,0,0],config),0)
        values=(33,17,29)
        rows=stage._mmr_terms(values,10)
        self.assertEqual(rows[0][6],(33*17*(29<<10))//(1<<20))
        self.assertEqual(rows[1][6],rows[0][6]**2//(1<<20))
        self.assertEqual(rows[2][6],rows[0][6]*rows[1][6]//(1<<20))
        config=stage.BaseMappingConfig(10,23,[identity,mmr([0,1023],[[0,0,0,0,0,0,1<<28]]),identity])
        self.assertEqual(stage.map_sample(1,[33,17,9],config),8)
        config=stage.BaseMappingConfig(10,23,[identity,mmr([0,1023],[[0]*7,[0,0,0,1<<32,0,0,0]]),identity])
        self.assertEqual(stage.map_sample(1,[200,190,0],config),44064)

    def test_near_full_scale_triple_all_orders_rational_known_answers(self):
        identity=poly([0,1023],[0,1<<23])
        for samples in ((1023,1023,1023),(1021,1019,1017),(997,1013,1023)):
            first=Fraction(samples[0]*samples[1]*samples[2],1024)
            first=first.numerator//first.denominator
            second=Fraction(first*first,1<<20)
            second=second.numerator//second.denominator
            third=Fraction(first*second,1<<20)
            third=third.numerator//third.denominator
            for order,feature in enumerate((first,second,third),1):
                rows=[[0]*7 for _ in range(order)]
                rows[-1][6]=1<<23
                source=[identity,mmr([0,1023],rows),identity]
                config=stage.BaseMappingConfig(10,23,source)
                expected=feature//16
                self.assertEqual(stage.map_sample(1,samples,config),expected)
                self.assertEqual(stage.map_sample(1,samples,config),reference.map_sample(1,samples,source,10,23))
        self.assertEqual((1023**3//1024)//16,65344)

    def test_immutable_copy_and_strict_metadata_validation(self):
        good=[poly([0,1023],[0,1<<23]) for _ in range(3)]
        config=stage.BaseMappingConfig(10,23,good)
        good[0]["pivots"][0]=512
        good[0]["segments"][0]["coefficients"][1]=0
        self.assertEqual(stage.map_sample(0,[1,0,0],config),64)
        with self.assertRaises(FrozenInstanceError): config.bit_depth=8
        self.assertEqual(stage.BaseMappingConfig(10,23,config.mappings),config)
        canonical=[poly([0,1023],[0,1<<23]) for _ in range(3)]
        for depth,denom in ((True,23),(10.0,23),(9,23),(10,True),(10,12),(10,33)):
            with self.assertRaises(ValueError): stage.BaseMappingConfig(depth,denom,canonical)
        invalid=[]
        for field,value in (("pivots",[0,0]),("pivots",[0,1024]),("pivots",[True,1023]),("segments",[])):
            trial=copy.deepcopy(canonical);trial[0][field]=value;invalid.append(trial)
        trial=copy.deepcopy(canonical);trial[0]["extra"]=0;invalid.append(trial)
        trial=copy.deepcopy(canonical);trial[0]=mmr([0,1023],[[0]*7]);invalid.append(trial)
        for coefficient in (True,1.0,Fraction(1),64<<23,-(64<<23)-1):
            trial=copy.deepcopy(canonical);trial[0]["segments"][0]["coefficients"][0]=coefficient;invalid.append(trial)
        for rows in ([],[[0]*6],[[0]*7]*4,[[1.0]*7]):
            trial=copy.deepcopy(canonical);trial[1]=mmr([0,1023],rows);invalid.append(trial)
        for trial in invalid:
            with self.assertRaises(ValueError): stage.BaseMappingConfig(10,23,trial)
        bad_compiled=(stage.ComponentMapping((0,1023),None),
                      stage.ComponentMapping((0,1023),({},)),
                      stage.ComponentMapping((0,1023),(stage.Segment("polynomial",(0,1<<23),1),)),
                      stage.ComponentMapping((0,1023),(stage.Segment("polynomial",(0,1<<23),True),)))
        for mapping in bad_compiled:
            with self.assertRaises(ValueError): stage.BaseMappingConfig(10,23,[mapping,*config.mappings[1:]])

    def test_samples_and_lazy_iterator(self):
        config=stage.BaseMappingConfig(10,23,[poly([0,1023],[0,1<<23]) for _ in range(3)])
        for values in ((0,0), (0,0,0,0), (True,0,0),(0.0,0,0),(Fraction(0),0,0),(-1,0,0),(1024,0,0)):
            with self.assertRaises(ValueError): stage.map_sample(0,values,config)
        for component in (True,0.0,-1,3):
            with self.assertRaises(ValueError): stage.map_sample(component,(0,0,0),config)
        consumed=[]
        def inputs():
            for sample in (1,2,1024):
                consumed.append(sample);yield (sample,0,0)
        result=stage.iter_mapped(0,inputs(),config)
        self.assertEqual(consumed,[])
        self.assertEqual(list(itertools.islice(result,2)),[64,128])
        self.assertEqual(consumed,[1,2])
        with self.assertRaises(ValueError):next(result)


if __name__=="__main__":unittest.main()
