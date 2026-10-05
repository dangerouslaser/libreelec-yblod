#!/usr/bin/env python3
"""Reusable standalone integer enhancement correction; not production wiring.

Arithmetic contract: signed accumulator, metadata cap, then signed floor.
Inputs are whole native EL codes only. No fractional-input interpretation,
transport rounding, shader emulation or final picture quantization is selected.
Field bounds are local arithmetic validation, not full bitstream legality.
"""
from collections.abc import Mapping
from dataclasses import dataclass


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: expected integer in [{low}, {high}]")
    return value


@dataclass(frozen=True)
class NLQConfig:
    bit_depth: int
    denominator: int
    offset: int
    slope: int
    threshold: int
    maximum: int

    def __post_init__(self):
        if type(self.bit_depth) is not int or self.bit_depth not in (8,10):
            raise ValueError("bit_depth must be integer8 or10")
        _integer(self.denominator,"denominator",self.bit_depth+5,32)
        _integer(self.offset,"offset",0,(1<<self.bit_depth)-1)
        for name in ("slope","threshold","maximum"):
            _integer(getattr(self,name),name,0,(2<<self.denominator)-1)

    @classmethod
    def from_mapping(cls, parameters, *, bit_depth, denominator):
        """Copy exactly the four supported metadata fields; no mutable alias."""
        if not isinstance(parameters,Mapping) or set(parameters) != {"offset","slope","threshold","maximum"}:
            raise ValueError("exactly offset/slope/threshold/maximum metadata fields required")
        return cls(bit_depth=bit_depth,denominator=denominator,**dict(parameters))


def _config(config):
    if type(config) is not NLQConfig:
        raise ValueError("validated NLQConfig required")
    return config


def correction(sample, config):
    """One integer EL sample to signed16bit-code-equivalent correction.

    These are correction units, not a16bit storage-range promise: the accepted
    coefficient envelope can produce wider outputs. No extra storage clamp.
    Python integer arithmetic avoids overflow. Division floors negative values;
    this is not truncation toward zero, and the cap precedes that division.
    """
    config = _config(config)
    sample = _integer(sample,"sample",0,(1<<config.bit_depth)-1)
    distance = sample-config.offset
    if not distance:
        return 0
    direction = 1 if distance > 0 else -1
    gain = 1 << (10-config.bit_depth)
    accumulator = ((2*distance-direction)*config.slope+2*direction*config.threshold)*gain
    limit = 2*gain*config.maximum
    bounded = min(limit,max(-limit,accumulator))
    return bounded // (1 << (config.denominator-5-config.bit_depth))


def iter_corrections(samples, config):
    """Lazy constant-memory correction iterator; validate each consumed sample."""
    _config(config)
    return (correction(sample,config) for sample in samples)


def iter_rows(rows, config):
    """Lazy row iterators, without buffering rows or a frame.

    Consume each yielded row before advancing a shared streaming source. Shape
    and three-channel pairing belong to the caller, not this scalar stage.
    """
    _config(config)
    return (iter_corrections(row,config) for row in rows)
