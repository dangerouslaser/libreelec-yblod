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


def triple_feature(codes, depth, order):
    """Exact isolated triple basis with required per-pass fixed-point floors."""
    y, u, v = codes
    pair = y*u*(1 << (20-2*depth))
    linear_v = v*(1 << (20-depth))
    first = pair*linear_v // (1 << 20)
    second = first*first // (1 << 20)
    return second if order == 2 else first*second // (1 << 20)


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
    # BL and EL depths are separate contracts, even with one denominator.
    # In particular the NLQ gain/shift must never use the BL bit depth.
    for bl_depth, el_depth in ((8, 10), (10, 8)):
        bl_top, el_top = (1 << bl_depth)-1, (1 << el_depth)-1
        mapping = config([poly((0, bl_top), (0, 1 << 23)) for _ in range(3)], bl_depth, 23)
        offset = 1 << (el_depth-1)
        nlq = NLQConfig(el_depth, 23, offset, 2048, 0, 1048576)
        triples = tuple((x, x, x) for x in (0, 1, bl_top//2, bl_top-1, bl_top))
        vectors.append(GPUVector(f"cross-depth-bl{bl_depth}-el{el_depth}", mapping, 1,
                                 triples, nlq, (0, offset-1, offset, offset+1, el_top), 12))
    # V2 MMR feature-floor and component coverage; no MMR is legal in Y/c0.
    for depth, order in ((8, 3), (10, 2)):
        top = (1 << depth)-1
        curves = [poly((0, top), (0, 1 << 32)) for _ in range(3)]
        rows = [[0]*7 for _ in range(order)]
        rows[order-1][6] = 1 << 37
        anchor = (top, top-2, top-1)
        constant = (1 << 31)-triple_feature(anchor, depth, order)*(1 << 17)
        curves[2]["segments"] = [dict(method="mmr", constant=constant, coefficients=rows)]
        triples = tuple(product((1, top-2, top-1, top), repeat=3))
        basis = "cube" if order == 3 else "square"
        vectors.append(GPUVector(f"mmr{order}-cr-b{depth}-triple-{basis}-floor", config(curves, depth, 32),
                                 2, triples, None, None, 12))
    curves = [poly((10, 990), (0, 1 << 23)), poly((100, 800), (0, 1 << 23)),
              dict(pivots=[100, 300, 700, 900], segments=[
                  dict(method="polynomial", coefficients=[1 << 19, 0]),
                  dict(method="mmr", constant=1 << 18,
                       coefficients=[[1 << 22, 0, 0, 0, 0, 0, 0]]),
                  dict(method="polynomial", coefficients=[1 << 20, 0])])]
    triples = tuple((1023, 0, code) for code in (0, 99, 100, 299, 300, 699, 700, 899, 900, 1023))
    vectors.append(GPUVector("mmr-mixed-pivot-right-and-guide-clamp", config(curves, 10, 23),
                             2, triples, None, None, 12))
    constant = 1 << 21
    positive = (WIDTH_LIMIT-constant)//2
    negative = WIDTH_LIMIT-constant-positive
    curves = [poly((0, 1023), (0, 1 << 32)) for _ in range(3)]
    curves[1]["segments"] = [dict(method="mmr", constant=constant,
                                  coefficients=[[positive, -negative, 0, 0, 0, 0, 0]])]
    triples = ((0, 0, 0), (1, 1, 1), (1023, 1023, 1023), (1023, 1022, 1), (1022, 1023, 1))
    vectors.append(GPUVector("mmr-width-limit-signed-prefix-cancellation", config(curves, 10, 32),
                             1, triples, None, None, 12))
    pivots = tuple(i*63 for i in range(16)) + (1023,)
    segments = []
    for index in range(16):
        if index % 2 == 0:
            segments.append(dict(method="mmr", constant=(index+1) << 19,
                                 coefficients=[[0, 1 << 20, 0, 0, 0, 0, 0]]))
        else:
            segments.append(dict(method="polynomial", coefficients=[(index+1) << 19, 0]))
    curves = [poly((0, 1023), (0, 1 << 23)) for _ in range(3)]
    curves[2] = dict(pivots=pivots, segments=segments)
    codes = sorted({max(0, min(1023, p+d)) for p in pivots for d in (-1, 0, 1)})
    triples = tuple(((index*37+100)%1024, (index*53+200)%1024, code)
                    for index, code in enumerate(codes))
    vectors.append(GPUVector("mmr-max-pivots-and-mixed-segments", config(curves, 10, 23),
                             2, triples, None, None, 12))
    return tuple(vectors)
