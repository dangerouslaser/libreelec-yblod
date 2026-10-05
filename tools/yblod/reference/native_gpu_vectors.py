"""Independent synthetic fixtures for an opt-in whole-code GPU diagnostic.

No context, dispatch, fractional policy or implicit backend fallback here.
Python stages provide the oracle; native CPU comparisons live in the tests.
"""
from dataclasses import dataclass
from itertools import product

from base_mapping_stage import BaseMappingConfig, map_sample
from nlq_stage import NLQConfig, correction
from composition_stage import compose_residual


WIDTH_LIMIT = (2**63 - 1) // 2**20


@dataclass(frozen=True)
class GPUVector:
    name: str
    mapping: BaseMappingConfig
    component: int
    triplets: tuple
    nlq: NLQConfig | None
    el_samples: tuple | None
    output_depth: int


def width_oracle(mapping):
    bounds = []
    first = (-1, -1)
    for component, curve in enumerate(mapping.mappings):
        for index, segment in enumerate(curve.segments):
            if segment.method != "mmr":
                continue
            bound = abs(segment.constant) + sum(abs(c) for row in segment.coefficients for c in row)
            bounds.append(bound)
            if bound > WIDTH_LIMIT and first == (-1, -1):
                first = (component, index)
    return dict(supported=first == (-1, -1), mmr_segment_count=len(bounds),
                worst_l1_bound=max(bounds, default=0), first_unsupported=first)


def expected_stages(vector):
    mapped = tuple(map_sample(vector.component, samples, vector.mapping) for samples in vector.triplets)
    if vector.nlq is None:
        if vector.el_samples is not None:
            raise ValueError("disabled fixture must not supply ignored EL")
        residual = (0,) * len(mapped)
    else:
        if vector.el_samples is None or len(vector.el_samples) != len(mapped):
            raise ValueError("fixture EL count mismatch")
        residual = tuple(correction(sample, vector.nlq) for sample in vector.el_samples)
    summed = tuple(a+b for a, b in zip(mapped, residual))
    reconstructed = tuple(compose_residual(a, b, vector.output_depth) for a, b in zip(mapped, residual))
    return mapped, residual, summed, reconstructed


def poly(pivots, coefficients):
    return dict(pivots=list(pivots), segments=[dict(method="polynomial", coefficients=list(coefficients))
                                             for _ in pivots[1:]])


def config(curves, depth, denominator):
    return BaseMappingConfig.from_mappings(curves, bit_depth=depth, denominator=denominator)


def vector_fixtures():
    vectors = []
    # Endpoint and native-depth transport, all components and both output depths.
    for depth in (8, 10):
        top = (1 << depth)-1
        triples = tuple(product((0, 1, top//2, top-1, top), repeat=3))
        mapping = config([poly((0, top), (0, 1 << 23)) for _ in range(3)], depth, 23)
        for component in range(3):
            for output_depth in (10, 12):
                vectors.append(GPUVector(f"identity-b{depth}-c{component}-o{output_depth}", mapping,
                                         component, triples, None, None, output_depth))
    # Deliberately discontinuous intervals establish right ownership at pivots.
    curves = [dict(pivots=[10, 100, 300, 900], segments=[
        dict(method="polynomial", coefficients=[coefficient, 0])
        for coefficient in (1 << 19, 1 << 20, 1 << 21)]) for _ in range(3)]
    mapping = config(curves, 10, 23)
    codes = (0, 9, 10, 99, 100, 299, 300, 899, 900, 1023)
    vectors.append(GPUVector("right-owned-pivots", mapping, 0,
                             tuple((x, 0, 0) for x in codes), None, None, 12))
    # Signed quadratic coefficients and high denominator stress 64-bit
    # polynomial products without reducing the evaluation to a constant.
    for name, coefficients in (
        ("signed-quadratic-d32", (1 << 22, 1 << 30, -(1 << 29))),
        ("polynomial-coefficient-extremes", (-(1 << 38), (1 << 38)-1, -(1 << 38))),
    ):
        mapping = config([poly((0, 1023), coefficients) for _ in range(3)], 10, 32)
        triples = tuple((x, x, x) for x in (0, 1, 2, 31, 32, 511, 512, 1021, 1022, 1023))
        vectors.append(GPUVector(name, mapping, 2, triples, None, None, 12))
    # Asymmetric per-channel endpoints affect explicit MMR luma guide too.
    for order in (1, 2, 3):
        curves = [poly((100, 900), (0, 1 << 23)), poly((200, 800), (0, 1 << 23)),
                  poly((300, 700), (0, 1 << 23))]
        rows = [[1 << 20, 1 << 22, -(1 << 19), 1234567, -234567, 345678, -456789]]
        rows.extend([[314159, -271828, 161803, -141421, 173205, -223606, 244948]
                     for _ in range(order-1)])
        curves[1]["segments"] = [dict(method="mmr", constant=1 << 18, coefficients=rows)]
        mapping = config(curves, 10, 23)
        triples = tuple(product((0, 1, 511, 1021, 1023), repeat=3))
        vectors.append(GPUVector(f"mmr{order}-all-channel-clamps", mapping, 1,
                                 triples, None, None, 12))
    # Cap before signed floor crosses the final half-round boundary.
    mapping = config([poly((0, 1023), (4096, 0)) for _ in range(3)], 10, 23)
    nlq = NLQConfig(10, 23, 512, 2048, 0, 1025)
    vectors.append(GPUVector("negative-cap-before-floor", mapping, 0,
                             ((0, 0, 0),)*5, nlq, (510, 511, 512, 513, 514), 12))
    # Wider denominator and coefficient boundaries; accepted/rejected width
    # is independent of whether the CPU's signed128 implementation accepts it.
    for bound in (WIDTH_LIMIT-1, WIDTH_LIMIT, WIDTH_LIMIT+1):
        curves = [poly((0, 1023), (0, 1 << 32)) for _ in range(3)]
        curves[1]["segments"] = [dict(method="mmr", constant=bound,
                                      coefficients=[[0]*7])]
        vectors.append(GPUVector(f"mmr-width-{bound}", config(curves, 10, 32), 1,
                                 ((0, 0, 0), (1023, 1023, 1023)), None, None, 12))
    for depth, denominator in ((8, 13), (10, 15), (10, 32)):
        top = (1 << depth)-1
        mapping = config([poly((0, top), (0, 1 << denominator)) for _ in range(3)], depth, denominator)
        bound = (2 << denominator)-1
        nlq = NLQConfig(depth, denominator, 1 << (depth-1), bound, bound, bound)
        triples = ((0, 0, 0), (1, 1, 1), (top//2, top//2, top//2), (top, top, top))
        vectors.append(GPUVector(f"nlq-extreme-b{depth}-d{denominator}", mapping, 0,
                                 triples, nlq, (0, 1, 1 << (depth-1), top), 10))
    return tuple(vectors)
