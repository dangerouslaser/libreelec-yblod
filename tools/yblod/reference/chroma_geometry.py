#!/usr/bin/env python3
"""Isolated 4:2:0 chroma-expansion experiments, not a playback implementation.

The existing prepared-left contract places chroma centers at (2*x, 2*y + .5)
in luma-sample coordinates. Preserve that geometry while changing ONLY the
vertical interpolation kernel. Horizontal interpolation always stays bilinear.
The top/bottom variants intentionally violate that contract as negative controls.

No RPU processing, colour conversion, code limiting, or rounding is performed.
Requires NumPy. Existing preparation and output modules are not modified.
"""
import numpy as np


VARIANTS = ("linear-left", "cubic-left", "linear-top-control", "linear-bottom-control")
WORK_ROWS = 32


def configuration(variant="linear-left"):
    """Return fresh JSON-safe experimental policy metadata, not mutable globals."""
    if variant not in VARIANTS:
        raise ValueError("unknown chroma geometry variant")
    cubic = variant == "cubic-left"
    center = {"linear-top-control": 0.0, "linear-bottom-control": 1.0}.get(variant, 0.5)
    vertical = ({"name": "Keys cubic", "a": -0.5, "offsets": [-1, 0, 1, 2],
                 "weights": "K(t-offset), t=coordinate-floor(coordinate)",
                 "kernel_d_abs_0_to_1": "1.5*d^3 - 2.5*d^2 + 1",
                 "kernel_d_abs_1_to_2": "-0.5*d^3 + 2.5*d^2 - 4*d + 2",
                 "kernel_d_abs_ge_2": "0"}
                if cubic else {"name": "linear", "offsets": [0, 1], "weights": ["1-t", "t"]})
    return {"schema": "yblod.chroma-geometry-experiment.v1", "variant": variant,
            "input_contract": "prepared planar 4:2:0 left-sited chroma",
            "output": "float64 planar full-resolution chroma strip",
            "source_centers_in_luma_coordinates": {"x": "2*i", "y": f"2*j+{center:g}"},
            "source_center_offsets_luma_samples": [0.0, center],
            "source_sample_spacing_luma_samples": [2, 2],
            "horizontal": {"name": "linear", "coordinate": "output_x/2",
                           "offsets": [0, 1], "weights": ["1-t", "t"],
                           "unchanged_from_output_frame_expand_left": True},
            "vertical": dict(vertical, coordinate=f"(global_output_y-{center:g})/2"),
            "boundary": "replicate edge samples; do not reset coordinates at strip boundaries",
            "arithmetic": "float64; no intermediate rounding or clipping",
            "invalid_geometry_control": center != 0.5,
            "production_choice": False,
            "accuracy_status": "isolated diagnostic; no claim of proprietary Dolby filter equivalence",
            "geometry_basis": "existing prepare_frame left-sited contract and output_frame.expand_left coordinates",
            "working_chunk_rows": WORK_ROWS}


def _cubic_weights(fraction):
    """Keys a=-.5 sampled at the four neighbors of floor(coordinate)."""
    weights = []
    for offset in (-1, 0, 1, 2):
        d = np.abs(fraction - offset)
        near = 1.5 * d**3 - 2.5 * d**2 + 1
        far = -0.5 * d**3 + 2.5 * d**2 - 4 * d + 2
        weights.append(np.where(d <= 1, near, np.where(d < 2, far, 0.0)))
    return weights


def _samples(a, indices):
    # Index first, then convert only the requested small set of rows. Casting
    # the entire source plane to float64 would defeat bounded-strip processing.
    result = a[indices].astype(np.float64, copy=False)
    if not np.all(np.isfinite(result)):
        raise ValueError("sampled chroma values must be finite")
    return result


def expand(a, start=0, stop=None, variant="linear-left"):
    """Return output rows [start, stop), evaluated in global luma coordinates.

    Output width/height are twice input width/height. Empty valid row intervals
    return an empty strip. Input must be a nonempty real numeric NumPy plane;
    only sampled input rows are checked for finite values. Internal temporaries
    are bounded to WORK_ROWS; the requested result itself must fit in memory.
    Callers processing 4K frames should request small strips, not the full output.
    """
    policy = configuration(variant)
    if not isinstance(a, np.ndarray) or a.ndim != 2 or 0 in a.shape or a.dtype.kind not in "uif":
        raise ValueError("expected a nonempty two-dimensional real numeric NumPy plane")
    h, w = a.shape
    stop = h * 2 if stop is None else stop
    for value in (start, stop):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError("strip bounds must be integers")
    if not 0 <= start <= stop <= 2 * h:
        raise ValueError("strip bounds lie outside the expanded plane")
    result = np.empty((stop - start, 2 * w), dtype=np.float64)
    center = policy["source_center_offsets_luma_samples"][1]
    x = np.arange(w * 2, dtype=np.float64) / 2
    ix = np.floor(x).astype(np.intp)
    fx = x - ix
    left, right = np.clip(ix, 0, w - 1), np.clip(ix + 1, 0, w - 1)
    for first in range(start, stop, WORK_ROWS):
        last = min(first + WORK_ROWS, stop)
        y = (np.arange(first, last, dtype=np.float64) - center) / 2
        iy = np.floor(y).astype(np.intp)
        fy = y - iy
        with np.errstate(over="raise", invalid="raise"):
            try:
                if variant == "cubic-left":
                    rows = np.zeros((last - first, w), dtype=np.float64)
                    for delta, weight in zip((-1, 0, 1, 2), _cubic_weights(fy)):
                        samples = _samples(a, np.clip(iy + delta, 0, h - 1))
                        samples *= weight[:, None]
                        rows += samples
                else:
                    # Keep the existing expand_left operation order, including
                    # separate products before addition, for baseline identity.
                    rows = (_samples(a, np.clip(iy, 0, h - 1)) * (1 - fy[:, None])
                            + _samples(a, np.clip(iy + 1, 0, h - 1)) * fy[:, None])
                result[first - start:last - start] = (rows[:, left] * (1 - fx)
                                                      + rows[:, right] * fx)
            except FloatingPointError as error:
                raise ValueError("chroma interpolation produced a non-finite value") from error
    return result
