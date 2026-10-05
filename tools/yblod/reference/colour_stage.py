#!/usr/bin/env python3
"""Scalar float64 colour-coordinate diagnostic, not display mapping or HDMI.

All matrices, offsets and PQ-domain policy are explicitly supplied. This
module has no NumPy, renderer, chroma-filter or device dependency. The project
4096 code convention is explicit and not a Dolby conformance assertion.
"""
from dataclasses import dataclass, field
import math
from numbers import Real

PQ_POLICIES = ("reject-outside-unit", "extend-positive-negative-to-zero")
M1, M2 = 2610 / 16384, 2523 / 32
C1, C2, C3 = 3424 / 4096, 2413 / 128, 2392 / 128


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("finite real number required")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError("finite real number required") from None
    if not math.isfinite(value):
        raise ValueError("finite real number required")
    return value


def _triple(values):
    if not isinstance(values, (tuple, list)) or len(values) != 3:
        raise ValueError("explicit three-component tuple/list required")
    return tuple(_finite(v) for v in values)


def _matrix(values):
    if not isinstance(values, (tuple, list)) or len(values) != 3:
        raise ValueError("explicit 3x3 matrix required")
    return tuple(_triple(row) for row in values)


def _mul(matrix, values):
    return tuple(_finite(sum(a * b for a, b in zip(row, values))) for row in matrix)


def _inverse(matrix):
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    cofactors = ((e*i-f*h, f*g-d*i, d*h-e*g),
                 (c*h-b*i, a*i-c*g, b*g-a*h),
                 (b*f-c*e, c*d-a*f, a*e-b*d))
    determinant = _finite(a*cofactors[0][0] + b*cofactors[0][1] + c*cofactors[0][2])
    if determinant == 0:
        raise ValueError("target matrix is singular")
    return tuple(tuple(_finite(cofactors[col][row] / determinant) for col in range(3))
                 for row in range(3))


def _pq_input(value, policy):
    value = _finite(value)
    if policy not in PQ_POLICIES:
        raise ValueError("declare supported PQ-domain policy")
    if policy == "reject-outside-unit" and not 0 <= value <= 1:
        raise ValueError("PQ input outside declared unit domain")
    return max(value, 0)


def pq_decode(value, *, policy):
    value = _pq_input(value, policy)
    p = value ** (1 / M2)
    denominator = C2 - C3 * p
    if denominator <= 0:
        raise ValueError("PQ decode outside finite extended domain")
    try:
        return _finite((max(p - C1, 0) / denominator) ** (1 / M1))
    except OverflowError:
        raise ValueError("PQ decode overflow") from None


def pq_encode(value, *, policy):
    value = _pq_input(value, policy)
    p = value ** M1
    return _finite(((C1 + C2 * p) / (1 + C3 * p)) ** M2)


@dataclass(frozen=True)
class ColourConfig:
    source_ycc: tuple
    source_offset: tuple
    source_lms: tuple
    target_ycc: tuple
    target_offset: tuple
    target_lms: tuple
    pq_policy: str
    code_scale: int
    target_ycc_inverse: tuple = field(init=False, repr=False)
    target_lms_inverse: tuple = field(init=False, repr=False)

    def __post_init__(self):
        if type(self.code_scale) is not int or self.code_scale != 4096:
            raise ValueError("this diagnostic requires explicit 4096 code scale")
        if self.pq_policy not in PQ_POLICIES:
            raise ValueError("declare supported PQ-domain policy")
        for name in ("source_ycc", "source_lms", "target_ycc", "target_lms"):
            object.__setattr__(self, name, _matrix(getattr(self, name)))
        for name in ("source_offset", "target_offset"):
            object.__setattr__(self, name, _triple(getattr(self, name)))
        object.__setattr__(self, "target_ycc_inverse", _inverse(self.target_ycc))
        object.__setattr__(self, "target_lms_inverse", _inverse(self.target_lms))

    @classmethod
    def from_dm(cls, dm, *, target_ycc, target_lms, target_offset, pq_policy, code_scale):
        """Supported source-DM subset only; not RPU/provenance validation."""
        if not isinstance(dm, dict) or type(dm.get("compressed")) is not bool or dm["compressed"]:
            raise ValueError("uncompressed source DM required")
        required = {"signal_eotf": 65535, "signal_eotf_param0": 0,
                    "signal_eotf_param1": 0, "signal_eotf_param2": 0,
                    "signal_bit_depth": 12, "signal_color_space": 0,
                    "signal_chroma_format": 0, "signal_full_range_flag": 1}
        for key, expected in required.items():
            if type(dm.get(key)) is not int or dm[key] != expected:
                raise ValueError(f"unsupported source {key}")
        def coefficient(key):
            value = dm.get(key)
            if type(value) is not int:
                raise ValueError(f"{key}: integer source coefficient required")
            return _finite(value)
        ycc = tuple(tuple(coefficient(f"ycc_to_rgb_coef{3*r+c}") / 8192 for c in range(3)) for r in range(3))
        lms = tuple(tuple(coefficient(f"rgb_to_lms_coef{3*r+c}") / 16384 for c in range(3)) for r in range(3))
        offset = tuple(coefficient(f"ycc_to_rgb_offset{i}") / 2**28 for i in range(3))
        return cls(ycc, offset, lms, target_ycc, target_offset, target_lms, pq_policy, code_scale)


@dataclass(frozen=True)
class ColourResult:
    source_nonlinear: tuple
    common_linear_lms: tuple
    target_linear: tuple
    transport_before_quantization: tuple
    codes: tuple


def convert_sample(codes, config):
    """Explicit reconstructed/expanded 12-bit components to target coordinates.

    Float components are allowed for separately performed chroma expansion.
    No chroma sampling, RGB gamut clipping or display tone mapping occurs here.
    """
    if type(config) is not ColourConfig:
        raise ValueError("validated ColourConfig required")
    codes = _triple(codes)
    if any(not 0 <= value <= 4095 for value in codes):
        raise ValueError("reconstructed/expanded input must stay in 0..4095")
    nonlinear = _mul(config.source_ycc, tuple(v / config.code_scale - o for v, o in zip(codes, config.source_offset)))
    common = _mul(config.source_lms, tuple(pq_decode(v, policy=config.pq_policy) for v in nonlinear))
    target_linear = _mul(config.target_lms_inverse, common)
    target = _mul(config.target_ycc_inverse, tuple(pq_encode(v, policy=config.pq_policy) for v in target_linear))
    target = tuple(_finite(v + o) for v, o in zip(target, config.target_offset))
    quantized = tuple(min(4095, max(0, math.floor(_finite(v * config.code_scale + 0.5)))) for v in target)
    return ColourResult(nonlinear, common, target_linear, target, quantized)


def iter_converted(samples, config):
    """Lazy constant-memory scalar diagnostic, not a real-time implementation."""
    if type(config) is not ColourConfig:
        raise ValueError("validated ColourConfig required")
    return (convert_sample(codes, config) for codes in samples)
