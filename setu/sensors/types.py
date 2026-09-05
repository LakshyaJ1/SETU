"""Sensor data contracts.

These are the boundary between "where the data came from" and "what the
estimator does with it". A simulated drive, a replayed IO-VNBD trip and a live
Android session all produce a :class:`SensorLog`, so the estimator never learns
which one it is looking at -- the property that makes the replay-determinism
requirement (``docs/04-architecture.md`` 4.1) testable at all.

Streams are stored as arrays rather than as per-sample objects. The real system
is a streaming C++ core; this twin is an offline analysis tool, and vectorised
storage is what makes a full-corpus sweep tractable in Python.

Time is seconds from session start on a **monotonic** clock. Wall-clock time is
deliberately absent: ``docs/04-architecture.md`` 4.4 requires monotonic
timestamps because an NTP step during a drive would corrupt integration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "ImuStream",
    "GnssStream",
    "BaroStream",
    "MagStream",
    "SensorLog",
    "GroundTruth",
    "tier_for_rate",
    "TIER_DESCRIPTIONS",
]


# Capability tiers, keyed to IMU sample rate (docs/04-architecture.md 4.3).
TIER_DESCRIPTIONS: dict[str, str] = {
    "A": ">=200 Hz - SVO full (orders 1-11), expect 0.5-1 %/km",
    "B": "50-200 Hz - SVO partial (orders 1-4), expect 1-2 %/km",
    "C": "10-50 Hz - SVO off; CTS and CSA only, expect 2-3 %/km",
    "D": "<10 Hz or no gyro - route extrapolation only",
}


def tier_for_rate(rate_hz: float, *, has_gyro: bool = True) -> str:
    """Capability tier for an IMU sample rate.

    This is an architectural switch, not a caveat: the tier decides whether SVO
    runs at all, and no accuracy number may be quoted without it
    (``docs/08-evaluation.md`` 8.1).
    """
    # Rates are measured from timestamps, so a nominal 10 Hz stream arrives as
    # 9.999999999999998 and would fall off the bottom of the table. The
    # tolerance is relative because the same applies at every boundary.
    rate_hz = float(rate_hz) * (1.0 + 1e-9)
    if not has_gyro or rate_hz < 10.0:
        return "D"
    if rate_hz < 50.0:
        return "C"
    if rate_hz < 200.0:
        return "B"
    return "A"


def _check(name: str, arr: np.ndarray, n: int, width: int | None = None) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    want = (n,) if width is None else (n, width)
    if arr.shape != want:
        raise ValueError(f"{name} must have shape {want}, got {arr.shape}")
    return arr


@dataclass(frozen=True)
class ImuStream:
    """Specific force and angular rate in the sensor body frame."""

    t: np.ndarray  # (N,) seconds
    accel: np.ndarray  # (N, 3) m/s^2, specific force (gravity included)
    gyro: np.ndarray  # (N, 3) rad/s

    def __post_init__(self) -> None:
        n = len(self.t)
        object.__setattr__(self, "accel", _check("accel", self.accel, n, 3))
        object.__setattr__(self, "gyro", _check("gyro", self.gyro, n, 3))
        if n > 1 and not np.all(np.diff(self.t) > 0):
            raise ValueError("IMU timestamps must be strictly increasing")

    @property
    def rate_hz(self) -> float:
        if len(self.t) < 2:
            return 0.0
        return float(1.0 / np.median(np.diff(self.t)))

    @property
    def tier(self) -> str:
        return tier_for_rate(self.rate_hz)

    def __len__(self) -> int:
        return len(self.t)


@dataclass(frozen=True)
class GnssStream:
    """GNSS epochs in the local ENU frame.

    ``available`` is the outage mask. Position and velocity are carried
    separately because Doppler velocity survives with 3-4 satellites while a
    position fix does not -- the graceful-degradation mechanism of
    ``docs/03-approach.md`` 3.9. The outage protocol withholds both
    (``docs/08-evaluation.md`` 8.1 step 3); withholding position alone would
    flatter the result.
    """

    t: np.ndarray  # (M,)
    pos_enu: np.ndarray  # (M, 3) m
    vel_enu: np.ndarray  # (M, 3) m/s
    pos_sigma: np.ndarray  # (M,) m, 1-sigma horizontal
    vel_sigma: np.ndarray  # (M,) m/s, 1-sigma
    available: np.ndarray  # (M,) bool - False during a simulated outage
    n_sats: np.ndarray  # (M,) int

    def __post_init__(self) -> None:
        m = len(self.t)
        object.__setattr__(self, "pos_enu", _check("pos_enu", self.pos_enu, m, 3))
        object.__setattr__(self, "vel_enu", _check("vel_enu", self.vel_enu, m, 3))
        object.__setattr__(self, "pos_sigma", _check("pos_sigma", self.pos_sigma, m))
        object.__setattr__(self, "vel_sigma", _check("vel_sigma", self.vel_sigma, m))
        object.__setattr__(self, "available", np.asarray(self.available, dtype=bool).reshape(m))
        object.__setattr__(self, "n_sats", np.asarray(self.n_sats, dtype=int).reshape(m))

    def __len__(self) -> int:
        return len(self.t)


@dataclass(frozen=True)
class BaroStream:
    """Barometric pressure. Resolves parking level (docs/03-approach.md 3.8)."""

    t: np.ndarray  # (K,)
    pressure_pa: np.ndarray  # (K,)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pressure_pa", _check("pressure_pa", self.pressure_pa, len(self.t))
        )

    def __len__(self) -> int:
        return len(self.t)


@dataclass(frozen=True)
class MagStream:
    """Magnetometer, body frame, microtesla. Feeds the EFA magnetic anchors."""

    t: np.ndarray  # (K,)
    field_ut: np.ndarray  # (K, 3)

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_ut", _check("field_ut", self.field_ut, len(self.t), 3))

    def __len__(self) -> int:
        return len(self.t)


@dataclass(frozen=True)
class SensorLog:
    """Everything the estimator is allowed to see."""

    imu: ImuStream
    gnss: GnssStream
    baro: BaroStream | None = None
    mag: MagStream | None = None
    source: str = "unknown"

    @property
    def tier(self) -> str:
        return self.imu.tier

    @property
    def duration_s(self) -> float:
        return float(self.imu.t[-1] - self.imu.t[0]) if len(self.imu) else 0.0


@dataclass(frozen=True)
class GroundTruth:
    """The answer. Never visible to the estimator; used only for scoring.

    Sampled on the IMU time grid so that error can be evaluated at any epoch
    without interpolating the truth.
    """

    t: np.ndarray  # (N,)
    s: np.ndarray  # (N,) arc length along the road, m
    v: np.ndarray  # (N,) speed along the path, m/s
    pos_enu: np.ndarray  # (N, 3)
    vel_enu: np.ndarray  # (N, 3)
    R_nb: np.ndarray  # (N, 3, 3) body -> navigation
    psi: np.ndarray  # (N,) heading, rad, unwrapped
    roll: np.ndarray  # (N,) rad; the lean angle for a two-wheeler
    kappa: np.ndarray  # (N,) path curvature, 1/m
    a_long: np.ndarray  # (N,) along-path acceleration, m/s^2
    a_lat: np.ndarray  # (N,) lateral acceleration, m/s^2
    omega_z: np.ndarray  # (N,) yaw rate about the true vertical, rad/s
    # What a perfect, perfectly mounted sensor would read. Still ground truth --
    # the estimator sees only the corrupted copies in SensorLog -- but it is what
    # the noise model is applied to, and what an ideal-sensor ablation replays.
    accel_ideal: np.ndarray  # (N, 3) specific force, vehicle frame
    gyro_ideal: np.ndarray  # (N, 3) angular rate, vehicle frame
    vehicle: str = "car"
    route: str = "unknown"

    def __len__(self) -> int:
        return len(self.t)

    def index_at(self, t: float) -> int:
        """Index of the truth sample nearest to time ``t``."""
        return int(np.searchsorted(self.t, t).clip(0, len(self.t) - 1))
