"""Exact point-polynomial oracle for experimental native chroma preparation.

Native top-left chroma at (2*x,2*y) becomes left-sited at (2*x,2*y+1/2)
by sampling each input column at y+1/4, leaving horizontal positions unchanged.
Linear and cubic are project experiments, not claimed Dolby-mandated filters.
The cubic is evaluated from endpoint values and centered endpoint slopes, not
from the production FIR coefficient array. Quantization is explicit: round
half toward positive infinity, then bound to native bit depth.

The coordinate-only Annex-B discussion below assumes the registration implied
by the existing vertical luma interpolation: EL sample u maps to BL2*u+1/2.
It does not establish that this is a proprietary decoder's actual registration.
"""
from fractions import Fraction as F


def point(column, coordinate, method):
    coordinate = F(coordinate)
    index = coordinate.numerator//coordinate.denominator
    t = coordinate-index
    at = lambda k: F(column[min(len(column)-1, max(0, k))])
    left, right = at(index), at(index+1)
    if method == "linear":
        return left + (right-left)*t
    if method != "cubic128":
        raise ValueError("unknown native preparation experiment")
    slope_left = (right-at(index-1))/2
    slope_right = (at(index+2)-left)/2
    # Solve polynomial endpoint/slope constraints, then evaluate the point.
    quadratic = 3*(right-left)-2*slope_left-slope_right
    cubic = 2*(left-right)+slope_left+slope_right
    return left + slope_left*t + quadratic*t*t + cubic*t*t*t


def round_half_up(value):
    shifted = F(value)+F(1, 2)
    return shifted.numerator//shifted.denominator


def native_phase(rows, method="linear", bit_depth=10):
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("nonempty rectangular samples required")
    maximum = 2**bit_depth-1
    if any(type(v) is not int or not 0 <= v <= maximum for row in rows for v in row):
        raise ValueError("native integer sample outside declared bit depth")
    unbounded = [[round_half_up(point([row[x] for row in rows], F(y)+F(1, 4), method))
                  for x in range(len(rows[0]))] for y in range(len(rows))]
    bounded = [[max(0, min(maximum, v)) for v in row] for row in unbounded]
    flat = [v for row in unbounded for v in row]
    return bounded, {"below_zero_before_bound": sum(v < 0 for v in flat),
                     "above_maximum_before_bound": sum(v > maximum for v in flat),
                     "unbounded_minimum": min(flat), "unbounded_maximum": max(flat)}


def annex_chroma_physical_y(output_chroma_row, native_shift=F(1, 4), post_shift=0):
    """Coordinate derivation only, not an alternative resampling implementation.

    Existing B chroma filter samples native row k/2-1/4. Native top-left
    chroma row j is physical BL4*j+1/2 under the stated luma registration.
    A post shift is measured in *output chroma rows*, not native rows.
    """
    native_coordinate = (F(output_chroma_row)+F(post_shift))/2-F(1, 4)+F(native_shift)
    return 4*native_coordinate+F(1, 2)
