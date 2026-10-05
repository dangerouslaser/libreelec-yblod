#!/usr/bin/env python3
"""Standalone integer composition stages; not production renderer integration.

Add signed enhancement correction to mapped BL, round once at the requested
output precision, then bound the final code. Transport/scaling and fractional
EL policy, colour/display adaptation and renderer integration are out of scope.
"""
from itertools import zip_longest

from nlq_stage import NLQConfig, correction


def _depth(output_depth):
    if type(output_depth) is not int or output_depth not in (10,12):
        raise ValueError("output_depth must be integer10 or12")
    return output_depth


def _mapped(mapped):
    if type(mapped) is not int or not 0 <= mapped <= 65535:
        raise ValueError("mapped BL must be integer in0..65535")
    return mapped


def compose_residual(mapped, residual, output_depth):
    """Compose explicit signed correction units, without a residual-storage cap.

    Rounding is integer half toward positive infinity, including negative sums.
    Bounding happens only after addition and rounding. Wide integer corrections
    remain intact; the caller controls how they were reconstructed.
    """
    mapped = _mapped(mapped)
    if type(residual) is not int:
        raise ValueError("residual must be signed integer, never float/bool")
    _depth(output_depth)
    step = 1 << (16-output_depth)
    rounded = (mapped+residual+step//2)//step
    return min((1<<output_depth)-1,max(0,rounded))


def compose(mapped, sample, config, output_depth):
    """Mapped BL plus integer EL correction; invalid EL never disables residual."""
    _mapped(mapped)
    _depth(output_depth)
    return compose_residual(mapped,correction(sample,config),output_depth)


def iter_composed(mapped_iter, el_iter, config, output_depth):
    """Lazy bounded-memory paired stream; reject either length mismatch.

    Validation of consumed values is lazy. A mismatch is raised when reached;
    previously yielded codes are not rolled back. Exhaust/validate a stream
    before publishing an output as complete.
    """
    if type(config) is not NLQConfig:
        raise ValueError("validated NLQConfig required")
    _depth(output_depth)
    sentinel = object()
    def values():
        for mapped,sample in zip_longest(mapped_iter,el_iter,fillvalue=sentinel):
            if mapped is sentinel or sample is sentinel:
                raise ValueError("mapped BL and EL streams have different lengths")
            yield compose(mapped,sample,config,output_depth)
    return values()


def iter_base_only(mapped_iter, output_depth):
    """Explicit residual-disabled path, separate from EL/config validation."""
    _depth(output_depth)
    return (compose_residual(mapped,0,output_depth) for mapped in mapped_iter)
