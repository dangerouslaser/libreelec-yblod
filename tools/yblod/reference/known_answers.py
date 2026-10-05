#!/usr/bin/env python3
"""Small, device-independent arithmetic oracles (standard library only).

This is validation code, not a playback implementation. It deliberately does
not import the implementation under test. Decimal (60 digits), Fraction, and
explicit 3x3 cofactors provide a separate numerical route from NumPy/float64.

Evidence levels must not be confused:
* PQ in [0, 1]: published ST 2084 equations/constants, also ITU-R BT.2100.
  https://www.itu.int/rec/R-REC-BT.2100
* Integer reconstruction: ETSI GS CCM 001 V1.1.1 clauses 5.4.2 / 5.4.3.
  See reference.py's specification URL. Synthetic samples below are ours.
* Transport matrices, 4096 code scale, half-up rounding, and final bounds:
  explicit project transport contract, NOT a Dolby conformance assertion.
* No oracle here chooses the correct treatment of out-of-domain source PQ,
  a display's tone mapping, or a proprietary chroma reconstruction filter.

There are no hardware captures, movie pixels, fitted offsets, or production
helpers in the expected-answer calculation. Inputs are tiny scalar triples.
"""
from decimal import Decimal, ROUND_FLOOR, localcontext
from fractions import Fraction
import json


def decimal(value):
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(value)


def pq_encode_unit(linear):
    """PQ for luminance / 10000 cd/m2, restricted to the documented domain."""
    with localcontext() as context:
        context.prec = 60
        linear = decimal(linear)
        if not 0 <= linear <= 1:
            raise ValueError("known-answer PQ requires 0..1")
        p = linear ** (Decimal(2610) / 16384)
        return +((Decimal(3424) / 4096 + Decimal(2413) / 128 * p)
                 / (1 + Decimal(2392) / 128 * p)) ** (Decimal(2523) / 32)


def pq_decode_unit(encoded):
    with localcontext() as context:
        context.prec = 60
        encoded = decimal(encoded)
        if not 0 <= encoded <= 1:
            raise ValueError("known-answer PQ requires 0..1")
        p = encoded ** (Decimal(32) / 2523)
        return +(max(Decimal(0), p - Decimal(3424) / 4096)
                 / (Decimal(2413) / 128 - Decimal(2392) / 128 * p)) ** (Decimal(16384) / 2610)


def solve3(coefficients, rhs):
    """Cramer's rule with exact integer determinants, not np.linalg.inv."""
    def determinant(a):
        return (a[0][0] * (a[1][1]*a[2][2] - a[1][2]*a[2][1])
                - a[0][1] * (a[1][0]*a[2][2] - a[1][2]*a[2][0])
                + a[0][2] * (a[1][0]*a[2][1] - a[1][1]*a[2][0]))

    den = determinant(coefficients)
    if den == 0:
        raise ValueError("singular known-answer matrix")
    answers = []
    for column in range(3):
        replaced = [[rhs[row] if col == column else decimal(coefficients[row][col])
                     for col in range(3)] for row in range(3)]
        answers.append(determinant(replaced) / decimal(den))
    return answers


def identity_source_transport(codes):
    """Synthetic identity source DM; independently evaluate target contract.

    Source matrices are identity, offsets zero. Individual channels are
    synthetic source-basis primaries, not named BT.2020 red/green/blue patches.
    All source codes here are <=4095, hence no source limiting decision enters.
    """
    with localcontext() as context:
        context.prec = 60
        common = [pq_decode_unit(Fraction(code, 4096)) for code in codes]
        linear = solve3(((17080, -348, -348), (-348, 17080, -348),
                         (-348, -348, 17080)), [v * 16384 for v in common])
        encoded = [pq_encode_unit(v) for v in linear]
        transport = solve3(((8194, 799, 1681), (8194, -933, 1091),
                            (8194, 267, -5545)), [v * 8192 for v in encoded])
        transport[1] += Decimal("0.5")
        transport[2] += Decimal("0.5")
        return tuple(max(0, min(4095, int((v * 4096 + Decimal("0.5"))
                                         .to_integral_value(rounding=ROUND_FLOOR))))
                     for v in transport)


# These names intentionally avoid claims about a particular display gamut.
COLOUR_INPUTS = {
    "black": (0, 0, 0),
    "dark_neutral": (256, 256, 256),
    "mid_neutral": (2048, 2048, 2048),
    "bright_neutral": (4095, 4095, 4095),
    "source_primary_1": (2048, 0, 0),
    "source_primary_2": (0, 2048, 0),
    "source_primary_3": (0, 0, 2048),
    "unequal_channels": (512, 1024, 1536),
}


if __name__ == "__main__":
    print(json.dumps({"scope": "synthetic arithmetic checks, not Dolby certification",
                      "transport_codes": {name: identity_source_transport(values)
                                          for name, values in COLOUR_INPUTS.items()},
                      "pq_100_nits": str(pq_encode_unit(Fraction(1, 100)))}, indent=2))
