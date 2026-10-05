"""Tiny exact geometry oracle; no NumPy, video pixels or renderer helpers.

Coordinates, not a claimed Dolby reconstruction filter:
420-left chroma samples sit at luma positions (2*x, 2*y+1/2). For full-size
pixel (x,y), native chroma coordinates are x/2 and y/2-1/4. Outside the source,
repeat edge samples. Linear is a controlled baseline; Catmull-Rom cubic is a
candidate. Neither is asserted to reproduce a proprietary scaler.

Cubic uses Hermite endpoint values/tangents instead of the production Keys
kernel sum. Fractions retain exact values, including negative overshoot.
The oracle can exercise either axis; the current production experiment varies
only the vertical filter and uses horizontal_kernel="linear" explicitly.
Offsets are *sampling-coordinate* offsets in luma pixels: positive dy samples
the source further down, i.e. moves the rendered feature up. Nonzero offsets
are deliberately wrong-phase controls, not proposed corrections.
"""
from fractions import Fraction as F


def interpolate(samples, coordinate, kernel="linear"):
    if not samples:
        raise ValueError("empty sample row")
    coordinate = F(coordinate)
    left = coordinate.numerator // coordinate.denominator
    t = coordinate-left

    def value(index):
        return F(samples[min(len(samples)-1, max(0, index))])

    a, b = value(left), value(left+1)
    if kernel == "linear":
        return a + (b-a)*t
    if kernel != "cubic":
        raise ValueError("unsupported geometry oracle kernel")
    tangent_a = (b-value(left-1))/2
    tangent_b = (value(left+2)-a)/2
    return ((2*t**3-3*t**2+1)*a + (t**3-2*t**2+t)*tangent_a
            + (-2*t**3+3*t**2)*b + (t**3-t**2)*tangent_b)


def expand(samples, kernel="linear", dx=0, dy=0, start=0, stop=None, horizontal_kernel=None):
    if not samples or not samples[0] or any(len(row) != len(samples[0]) for row in samples):
        raise ValueError("nonempty rectangular plane required")
    height, width = len(samples), len(samples[0])
    stop = height*2 if stop is None else stop
    if not 0 <= start <= stop <= height*2:
        raise ValueError("invalid strip")
    horizontal_kernel = kernel if horizontal_kernel is None else horizontal_kernel
    horizontal = [[interpolate(row, (F(x)+F(dx))/2, horizontal_kernel) for x in range(width*2)]
                  for row in samples]
    return [[interpolate([row[x] for row in horizontal], (F(y)+F(dy))/2-F(1, 4), kernel)
             for x in range(width*2)] for y in range(start, stop)]
