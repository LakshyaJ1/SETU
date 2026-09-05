"""CTS -- the Coordinated-Turn Speedometer.

In a turn, lateral acceleration and yaw rate determine speed outright:
``a_lat = v * Omega``, so ``v = a_lat / Omega``. No integration, no prior speed,
no scale factor -- which makes CTS the *absolute* reference that calibrates
SVO's unknown ``R_eff`` (``docs/03-approach.md`` 3.4). Turns calibrate the
odometer; the odometer carries the straights.

Two forms are implemented, and the distinction between them is the practical
heart of this module:

:func:`levelled_speed` is the general one. Given attitude it works for any
vehicle, leaning or not, because rotating the specific force into the
navigation frame removes gravity and lean together. This is the form the
pipeline uses.

:func:`lean_corrected_speed` is the attitude-free fallback for two-wheelers,
recovering the lean angle from the specific force itself. It exists because a
motorcycle's lateral accelerometer channel reads approximately zero in a turn:
the naive ratio returns *zero speed in every turn*, and a system that has not
thought about this will be silently, confidently wrong.

Neither form works on a straight road -- the division by ``Omega`` is
unobservable there, and the gate below reports that rather than returning a
number nobody should use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.constants import G0
from .types import ScalarMeasurement

__all__ = ["CtsConfig", "levelled_speed", "lean_corrected_speed"]


@dataclass(frozen=True)
class CtsConfig:
    """Gates and noise assumptions.

    ``min_yaw_rate`` is the important one. Below about 3 deg/s the division by
    ``Omega`` amplifies sensor noise without bound, so the gate is not a
    convenience -- it is what stops CTS from injecting a wild speed into the
    filter on a straight road.
    """

    min_yaw_rate: float = 0.05  # rad/s, ~2.9 deg/s
    min_lean_deg: float = 8.0  # two-wheeler form: below this |f| - g is under the noise

    # Residual accelerometer error, *including the part of the bias the filter
    # has not yet estimated*. White noise after 1 s of averaging is only about
    # 0.02 m/s^2, but a phone's turn-on bias is 0.05-0.13 m/s^2, and it is the
    # bias that dominates: measured against the simulator, using the white-noise
    # figure here reported sigma = 0.05 m/s against a true error of 0.30 m/s.
    # An overconfident covariance is worse than a large one.
    sigma_accel: float = 0.10  # m/s^2
    sigma_gyro: float = 1.5e-3  # rad/s, likewise bias-inclusive
    # Attitude error leaks gravity into the lateral channel at g * tilt, so a
    # 0.3 deg tilt error is already 0.05 m/s^2.
    sigma_tilt_rad: float = 0.005
    smooth_s: float = 1.0  # averaging window
    max_speed_mps: float = 60.0


def _smooth(x: np.ndarray, rate_hz: float, seconds: float) -> np.ndarray:
    """Zero-phase boxcar average along axis 0."""
    k = max(int(round(seconds * rate_hz)), 1)
    if k <= 1:
        return x
    pad_lo = np.repeat(x[:1], k // 2, axis=0)
    pad_hi = np.repeat(x[-1:], k - k // 2 - 1, axis=0)
    padded = np.concatenate([pad_lo, x, pad_hi], axis=0)
    kernel = np.ones(k) / k
    if x.ndim == 1:
        return np.convolve(padded, kernel, mode="valid")
    return np.stack(
        [np.convolve(padded[:, i], kernel, mode="valid") for i in range(x.shape[1])], axis=1
    )


def levelled_speed(
    t: np.ndarray,
    accel_body: np.ndarray,
    gyro_body: np.ndarray,
    R_nb: np.ndarray,
    heading: np.ndarray,
    *,
    config: CtsConfig | None = None,
) -> ScalarMeasurement:
    """Speed from the coordinated-turn relation, using the attitude estimate.

    Rotating into the navigation frame is what makes this work for a leaning
    two-wheeler as well as a car with no extra cases: the lean is already in
    ``R_nb``, so removing gravity in the navigation frame removes its projection
    onto the lateral axis too. Reading the body lateral channel instead is a
    ~12 % error on a car rolling a mere 1.4 degrees, because ``g sin(1.4 deg)``
    is a tenth of the lateral acceleration being measured.

    ``R_nb`` is the *estimated* attitude in the pipeline. Attitude error
    therefore propagates into CTS; a tilt error of ``eps`` leaks ``g * eps``
    into the lateral channel, which is why the filter's attitude covariance
    belongs in this sigma and is included below.
    """
    cfg = config or CtsConfig()
    t = np.asarray(t, dtype=float)
    rate = 1.0 / float(np.median(np.diff(t))) if len(t) > 1 else 100.0

    accel = _smooth(np.asarray(accel_body, dtype=float), rate, cfg.smooth_s)
    gyro = _smooth(np.asarray(gyro_body, dtype=float), rate, cfg.smooth_s)

    # Navigation-frame acceleration, gravity removed.
    a_nav = np.einsum("nij,nj->ni", R_nb, accel)
    a_nav[:, 2] -= G0
    left = np.stack([-np.sin(heading), np.cos(heading)], axis=1)
    a_lat = np.einsum("ni,ni->n", a_nav[:, :2], left)

    # Yaw rate about the true vertical, not the body z axis. For a leaning bike
    # these differ by cos(lean), which is a 4 % error at 16 degrees.
    omega = np.einsum("nij,nj->ni", R_nb, gyro)[:, 2]

    turning = np.abs(omega) > cfg.min_yaw_rate
    safe_omega = np.where(turning, omega, np.nan)
    v = a_lat / safe_omega

    # Error propagation for the ratio. Three contributions to the numerator:
    # accelerometer residual, gravity leaked through attitude error, and the
    # lag the averaging window introduces when the lateral acceleration is
    # changing fast (entering or leaving a bend), where a_lat and Omega are
    # smoothed but their transients do not line up.
    jerk = np.abs(np.gradient(a_lat, t)) if len(t) > 2 else np.zeros_like(a_lat)
    sigma_a_eff = np.sqrt(
        cfg.sigma_accel**2
        + (G0 * cfg.sigma_tilt_rad) ** 2
        + (0.5 * cfg.smooth_s * jerk) ** 2
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        sigma = np.sqrt(
            (sigma_a_eff / np.abs(safe_omega)) ** 2
            + (v * cfg.sigma_gyro / np.abs(safe_omega)) ** 2
        )

    valid = turning & np.isfinite(v) & (v > 0.0) & (v < cfg.max_speed_mps)
    return ScalarMeasurement(
        t=t,
        value=np.where(valid, v, np.nan),
        sigma=np.where(valid, sigma, np.inf),
        valid=valid,
        source="cts",
    )


def lean_corrected_speed(
    t: np.ndarray,
    accel_body: np.ndarray,
    gyro_body: np.ndarray,
    *,
    config: CtsConfig | None = None,
) -> ScalarMeasurement:
    """Two-wheeler speed without an attitude estimate.

    A motorcycle in a coordinated turn leans until the resultant runs along its
    own vertical, so::

        |f_yz| = g / cos(phi)          =>  phi   = arccos(g / |f_yz|)
        Omega  = w_z / cos(phi)        =>  v     = g sin(phi) / w_z

    The lean angle is read from the **y-z plane only**. The compact form in
    ``docs/03-approach.md`` 3.4 uses the full ``|f|``, which quietly assumes the
    rider is neither accelerating nor braking; on a roundabout they are doing
    both, and a 2 m/s^2 longitudinal term inflates ``|f|`` enough to bias the
    lean angle badly.

    Dropping the ``cos(phi)`` that converts body yaw rate to true yaw rate is a
    4 % scale error -- 40 m per kilometre -- and it is silent, which is why this
    is a named function with its own tests rather than three lines inline.
    """
    cfg = config or CtsConfig()
    t = np.asarray(t, dtype=float)
    rate = 1.0 / float(np.median(np.diff(t))) if len(t) > 1 else 100.0

    accel = _smooth(np.asarray(accel_body, dtype=float), rate, cfg.smooth_s)
    gyro = _smooth(np.asarray(gyro_body, dtype=float), rate, cfg.smooth_s)

    f_yz = np.linalg.norm(accel[:, 1:], axis=1)
    w_z = gyro[:, 2]

    ratio = np.clip(G0 / np.maximum(f_yz, 1e-9), -1.0, 1.0)
    phi = np.arccos(ratio)

    leaning = phi > np.radians(cfg.min_lean_deg)
    turning = np.abs(w_z) > cfg.min_yaw_rate
    usable = leaning & turning

    safe_w = np.where(usable, np.abs(w_z), np.nan)
    v = G0 * np.sin(phi) / safe_w

    # phi is recovered from |f_yz|, so accelerometer noise enters through
    # d(phi)/d|f| = cos(phi)^2 / (g sin(phi)) -- badly conditioned at small lean,
    # which is the reason for the lean gate rather than just the yaw-rate gate.
    with np.errstate(invalid="ignore", divide="ignore"):
        dphi = cfg.sigma_accel * np.cos(phi) ** 2 / (G0 * np.maximum(np.sin(phi), 1e-6))
        rel = np.sqrt(
            (dphi / np.maximum(np.tan(phi), 1e-6)) ** 2
            + (cfg.sigma_gyro / np.abs(safe_w)) ** 2
        )
        sigma = np.abs(v) * rel
        # Same averaging-lag term as the levelled form.
        if len(t) > 2:
            jerk = np.abs(np.gradient(G0 * np.tan(phi), t))
            sigma = np.sqrt(sigma**2 + (0.5 * cfg.smooth_s * jerk / np.abs(safe_w)) ** 2)

    valid = usable & np.isfinite(v) & (v > 0.0) & (v < cfg.max_speed_mps)
    return ScalarMeasurement(
        t=t,
        value=np.where(valid, v, np.nan),
        sigma=np.where(valid, sigma, np.inf),
        valid=valid,
        source="cts_lean",
    )
