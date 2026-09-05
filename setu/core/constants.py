"""Physical and geodetic constants.

Values are the standard ones; they are named here rather than inlined so that a
reviewer can check them in one place and so that no module silently disagrees
with another about the value of gravity.
"""

from __future__ import annotations

import numpy as np

# Standard gravity (CGPM 1901). docs/03-approach.md uses this exact value in the
# lean-angle relations, so CTS and the simulator must share it to the last digit.
G0: float = 9.80665

# WGS-84 ellipsoid.
WGS84_A: float = 6378137.0
WGS84_F: float = 1.0 / 298.257223563
WGS84_E2: float = WGS84_F * (2.0 - WGS84_F)

# Numerical thresholds. SMALL_ANGLE is where SO(3) series expansions take over
# from the closed forms; below it the closed forms lose precision to 0/0.
SMALL_ANGLE: float = 1e-7
EPS: float = float(np.finfo(np.float64).eps)

__all__ = ["G0", "WGS84_A", "WGS84_F", "WGS84_E2", "SMALL_ANGLE", "EPS"]
