"""Independent scalar checks for the informative CCM Annex B EL example.

No NumPy or production filter arrays. Luma vertical values come from Hermite
endpoint constraints; chroma uses point-linear interpolation. The specified
eight-tap horizontal filter is written as symmetric pairs of exact Fractions.
Each pass rounds half toward positive infinity, then bounds to unsigned16.

Coordinates refer to the supplied plane, NOT its physical registration to BL.
In particular this module does not apply the experimental native chroma phase
adapter or establish a licensed player's implementation/conformance.
"""
from fractions import Fraction as F


def round_bound(value):
    shifted = F(value)+F(1, 2)
    rounded = shifted.numerator//shifted.denominator
    return max(0, min(65535, rounded)), rounded


def _sample(samples, index):
    return F(samples[min(len(samples)-1, max(0, index))])


def vertical_point(samples, output_row, component):
    """Interior affine ramps evaluate at output_row/2-1/4 in native rows."""
    coordinate = F(output_row, 2)-F(1, 4)
    index = coordinate.numerator//coordinate.denominator
    t = coordinate-index
    left, right = _sample(samples, index), _sample(samples, index+1)
    if component in ("Cb", "Cr"):
        return left*(1-t)+right*t
    if component != "Y":
        raise ValueError("unknown component")
    slope_left = (right-_sample(samples, index-1))/2
    slope_right = (_sample(samples, index+2)-left)/2
    return ((2*t**3-3*t*t+1)*left + (t**3-2*t*t+t)*slope_left
            + (-2*t**3+3*t*t)*right + (t**3-t*t)*slope_right)


def horizontal_point(samples, output_column):
    index, odd = divmod(output_column, 2)
    if not odd:
        return _sample(samples, index)
    # Annex B midpoint FIR, paired about index+1/2. This is not equivalent
    # to the four-point vertical polynomial. Sum is 1, first moment is 1/2.
    return (F(11, 2048)*(_sample(samples, index-3)+_sample(samples, index+4))
            + F(47, 2048)*(_sample(samples, index-2)+_sample(samples, index+3))
            - F(131, 1024)*(_sample(samples, index-1)+_sample(samples, index+2))
            + F(307, 512)*(_sample(samples, index)+_sample(samples, index+1)))


def _stats(values):
    flat = [v for row in values for v in row]
    return {"below_zero_before_bound": sum(v < 0 for v in flat),
            "above_maximum_before_bound": sum(v > 65535 for v in flat),
            "unbounded_minimum": min(flat), "unbounded_maximum": max(flat)}


def expand(rows, component):
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("nonempty rectangular samples required")
    if component not in ("Y", "Cb", "Cr"):
        raise ValueError("unknown component")
    if any(type(v) is not int or not 0 <= v <= 65535 for row in rows for v in row):
        raise ValueError("unsigned16 integer samples required")
    columns = list(zip(*rows))
    vertical_pairs = [[round_bound(vertical_point(column, y, component)) for column in columns]
                      for y in range(len(rows)*2)]
    vertical = [[pair[0] for pair in row] for row in vertical_pairs]
    horizontal_pairs = [[round_bound(horizontal_point(row, x)) for x in range(len(row)*2)]
                        for row in vertical]
    output = [[pair[0] for pair in row] for row in horizontal_pairs]
    stats = {"vertical_even": _stats([[pair[1] for pair in row] for row in vertical_pairs[::2]]),
             "vertical_odd": _stats([[pair[1] for pair in row] for row in vertical_pairs[1::2]]),
             "horizontal_odd": _stats([[pair[1] for pair in row[1::2]] for row in horizontal_pairs])}
    return output, vertical, stats


def upsample_el(samples, component):
    """Two-result convenience API for independent synthetic corpus consumers."""
    output, vertical, _ = expand(samples, component)
    return output, vertical
