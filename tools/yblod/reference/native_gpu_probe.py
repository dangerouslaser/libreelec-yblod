#!/usr/bin/env python3
"""Synthetic fixture encoder only; GPU execution and arithmetic are native C/GLSL."""
import argparse
from pathlib import Path
import struct

import native_stage as native


def encode(mapping_config,nlq_config,component,triplets,el_samples,output_depth):
    checked, mapping=native._mapping(mapping_config)
    component=native._integer(component,"component",0,2)
    if type(output_depth) is not int or output_depth not in (10,12):
        raise ValueError("output_depth must be10 or12")
    rows=[]
    for row in triplets:
        if len(rows)==4096:raise ValueError("probe limit4096")
        if type(row) not in (tuple,list) or len(row)!=3:raise ValueError("three native BL codes required")
        rows.append(tuple(native._integer(v,"BL code",0,(1<<checked.bit_depth)-1) for v in row))
    if not rows:raise ValueError("nonempty fixture required")
    enabled=nlq_config is not None
    if enabled:
        corrected,_=native._nlq(nlq_config)
        if corrected.denominator!=checked.denominator:raise ValueError("denominator mismatch")
        if el_samples is None:raise ValueError("EL required")
        enhancement=[]
        for value in el_samples:
            if len(enhancement)>=len(rows):raise ValueError("extra EL samples")
            enhancement.append(native._integer(value,"EL code",0,(1<<corrected.bit_depth)-1))
        if len(enhancement)!=len(rows):raise ValueError("EL length mismatch")
        header=(corrected.bit_depth,corrected.offset,corrected.slope,corrected.threshold,corrected.maximum)
    else:
        if el_samples is not None:raise ValueError("disabled EL requires no samples")
        enhancement=[0]*len(rows);header=(0,0,0,0,0)
    data=bytearray(b"YBGPU01\0")
    data.extend(struct.pack("<8I3Q",len(rows),component,int(enabled),output_depth,
        checked.bit_depth,checked.denominator,*header))
    for curve in mapping.components:
        data.extend(struct.pack("<18i",curve.pivot_count,*curve.pivots))
        for segment in curve.segments:
            data.extend(struct.pack("<ii22q",segment.method,segment.order,segment.constant,
                                    *(value for row in segment.coefficients for value in row)))
    for row,el in zip(rows,enhancement):data.extend(struct.pack("<4I",*row,el))
    return bytes(data)


def write_fixture(path,*args):
    data=encode(*args)
    with Path(path).open("xb") as stream:stream.write(data)
    return len(data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory")
    args=parser.parse_args()
    from native_gpu_vectors import vector_fixtures
    root=Path(args.output_directory);root.mkdir()
    for fixture in vector_fixtures():
        write_fixture(root/(fixture.name+".bin"),fixture.mapping,fixture.nlq,fixture.component,
                      fixture.triplets,fixture.el_samples,fixture.output_depth)


if __name__=="__main__":main()
