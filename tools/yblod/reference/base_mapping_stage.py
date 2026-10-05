#!/usr/bin/env python3
"""Standalone integer BL mapping; independent of the reference implementation.

MMR callers provide their explicit luma guide in each Y/Cb/Cr triplet. This
stage neither samples nor chooses that guide. Denominator13..32 covers the
supported global contract; frame validation must additionally enforce
denominator >= ELbitdepth+5. Field bounds do not establish bitstream legality.
"""
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass


def _int(value,name,low,high):
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f"{name}: expected integer in [{low},{high}]")
    return value


@dataclass(frozen=True)
class Segment:
    method: str
    coefficients: tuple
    constant: int = 0


@dataclass(frozen=True)
class ComponentMapping:
    pivots: tuple
    segments: tuple


@dataclass(frozen=True)
class BaseMappingConfig:
    bit_depth: int
    denominator: int
    mappings: tuple

    def __post_init__(self):
        if type(self.bit_depth) is not int or self.bit_depth not in (8,10):
            raise ValueError("bit_depth must be integer8 or10")
        _int(self.denominator,"denominator",13,32)
        source=self.mappings
        if type(source) not in (tuple,list) or len(source)!=3:
            raise ValueError("exactly three component mappings required")
        frozen=[]
        for component,mapping in enumerate(source):
            if isinstance(mapping,ComponentMapping):
                if type(mapping.segments) not in (tuple,list) or any(type(s) is not Segment for s in mapping.segments):
                    raise ValueError("compiled mapping requires Segment sequence")
                for segment in mapping.segments:
                    if segment.method=="polynomial":
                        _int(segment.constant,"polynomial compiled constant",0,0)
                mapping={"pivots":mapping.pivots,"segments":[
                    dict(method=s.method,coefficients=s.coefficients,**({"constant":s.constant} if s.method=="mmr" else {}))
                    for s in mapping.segments]}
            if not isinstance(mapping,Mapping) or set(mapping)!={"pivots","segments"}:
                raise ValueError("mapping requires exactly pivots/segments")
            pivots=mapping["pivots"]
            if type(pivots) not in (tuple,list) or not 2<=len(pivots)<=17:
                raise ValueError("2..17 pivots required")
            pivots=tuple(_int(v,"pivot",0,(1<<self.bit_depth)-1) for v in pivots)
            if any(a>=b for a,b in zip(pivots,pivots[1:])):
                raise ValueError("pivots must strictly increase")
            segments=mapping["segments"]
            if type(segments) not in (tuple,list) or len(segments)!=len(pivots)-1:
                raise ValueError("one segment per interval required")
            compiled=[]
            for segment in segments:
                if not isinstance(segment,Mapping): raise ValueError("segment must be mapping")
                method=segment.get("method")
                keys={"method","coefficients"} if method=="polynomial" else {"method","coefficients","constant"}
                if set(segment)!=keys: raise ValueError("unsupported segment fields")
                coeffs=segment["coefficients"]
                if type(coeffs) not in (tuple,list): raise ValueError("coefficients must be sequence")
                if method=="polynomial":
                    if len(coeffs) not in (2,3): raise ValueError("linear/quadratic polynomial required")
                    bound=64<<self.denominator
                    compiled.append(Segment(method,tuple(_int(v,"polynomial coefficient",-bound,bound-1) for v in coeffs)))
                elif method=="mmr" and component!=0:
                    if not 1<=len(coeffs)<=3: raise ValueError("MMR requires1..3 orders")
                    bound=65536<<self.denominator
                    rows=[]
                    for row in coeffs:
                        if type(row) not in (tuple,list) or len(row)!=7: raise ValueError("MMR order requires7 coefficients")
                        rows.append(tuple(_int(v,"MMR coefficient",-bound,bound-1) for v in row))
                    constant=_int(segment["constant"],"MMR constant",-bound,bound-1)
                    compiled.append(Segment(method,tuple(rows),constant))
                else: raise ValueError("unsupported method; MMR is chroma-only")
            frozen.append(ComponentMapping(pivots,tuple(compiled)))
        object.__setattr__(self,"mappings",tuple(frozen))

    @classmethod
    def from_mappings(cls,mappings,*,bit_depth,denominator):
        return cls(bit_depth,denominator,mappings)


def _config(config):
    if type(config) is not BaseMappingConfig: raise ValueError("validated BaseMappingConfig required")


def _mmr_terms(values,depth):
    y,u,v=values
    first=[n<<(20-depth) for n in values]
    first.extend(a*b<<(20-2*depth) for a,b in ((y,u),(y,v),(u,v)))
    first.append((first[3]*first[2])//(1<<20))
    second=[n*n<<(20-2*depth) for n in values]
    second.extend(n*n//(1<<20) for n in first[3:])
    third=[a*b//(1<<20) for a,b in zip(first,second)]
    return first,second,third


def map_sample(component,samples,config):
    _config(config)
    _int(component,"component index",0,2)
    if type(samples) not in (tuple,list) or len(samples)!=3:
        raise ValueError("explicit Y/Cb/Cr integer triplet required")
    codes=tuple(_int(v,"sample",0,(1<<config.bit_depth)-1) for v in samples)
    mapping=config.mappings[component]
    index=max(0,min(len(mapping.segments)-1,bisect_right(mapping.pivots,codes[component])-1))
    segment=mapping.segments[index]
    bounded=tuple(min(m.pivots[-1],max(m.pivots[0],v)) for v,m in zip(codes,config.mappings))
    if segment.method=="polynomial":
        value=bounded[component]
        total=sum(coefficient*value**power*(1<<(20-config.bit_depth*power))
                  for power,coefficient in enumerate(segment.coefficients))
    else:
        total=segment.constant*(1<<20)
        terms=_mmr_terms(bounded,config.bit_depth)
        for coefficients,row in zip(segment.coefficients,terms):
            total+=sum(a*b for a,b in zip(coefficients,row))
    return min(65535,max(0,total//(1<<(config.denominator+4))))


def iter_mapped(component,sample_triplets,config):
    """Lazy constant-memory mapping; no implicit luma-guide selection."""
    _config(config)
    _int(component,"component index",0,2)
    return (map_sample(component,samples,config) for samples in sample_triplets)
