"""Sensor error models and the end-to-end drive simulator.

The estimator is handed a :class:`~setu.sensors.types.SensorLog` and nothing
else. Everything that makes real navigation hard is injected here: an unknown
phone mount, turn-on bias, bias random walk, scale-factor error, band-limiting
at the reported sample rate, GNSS outages, and a magnetic field with a
repeatable local anomaly.

The band-limiting deserves a note, because it is what makes the capability
tiers real rather than asserted. A phone reporting at 10 Hz is not aliasing the
axle harmonics down into its passband -- it has an anti-alias filter, and the
lines are simply *gone*. Simulating that faithfully is what makes "SVO is
impossible at Tier C" (``docs/04-architecture.md`` 4.3) a demonstrated fact of
this codebase rather than a claim in a document.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import decimate

from ..core import so3
from ..mapping.road import RoadPath
from ..mapping.routes import build_route
from ..sensors.types import BaroStream, GnssStream, GroundTruth, ImuStream, MagStream, SensorLog
from .truth import GradeFn, flat, simulate_truth
from .vehicle import CAR, VehicleModel
from .vibration import ROAD_NORMAL, VibrationModel, synthesize_vibration

__all__ = [
    "ImuErrorModel",
    "GnssErrorModel",
    "MountModel",
    "DriveResult",
    "PHONE_FLAGSHIP",
    "PHONE_MID",
    "PHONE_BUDGET",
    "PHONE_THROTTLED",
    "ADIS16505",
    "FOG",
    "DEVICES",
    "GNSS_OPEN_SKY",
    "GNSS_URBAN",
    "simulate_drive",
]

# Sea-level reference for the hypsometric conversion.
P0_PA = 101325.0
DEG = np.pi / 180.0


@dataclass(frozen=True)
class ImuErrorModel:
    """Inertial sensor error budget.

    Noise densities are the datasheet quantity (per root hertz), so the
    per-sample noise depends on the rate -- which is why a faster device is
    quieter per unit time as well as spectrally richer.
    """

    name: str
    rate_hz: float
    accel_noise_density: float  # m/s^2/sqrt(Hz)
    accel_bias0: float  # m/s^2, 1-sigma turn-on bias
    accel_bias_rw: float  # m/s^2/sqrt(s)
    gyro_noise_density: float  # rad/s/sqrt(Hz)
    gyro_bias0: float  # rad/s, 1-sigma turn-on bias
    gyro_bias_rw: float  # rad/s/sqrt(s)
    accel_scale_ppm: float = 5000.0
    gyro_scale_ppm: float = 3000.0
    has_baro: bool = True


# A flagship phone driven through SensorDirectChannel. Tier A: SVO can see
# axle orders 1-11.
PHONE_FLAGSHIP = ImuErrorModel(
    name="phone_flagship",
    rate_hz=400.0,
    accel_noise_density=0.0028,
    accel_bias0=0.045,
    accel_bias_rw=0.0009,
    gyro_noise_density=2.1e-4,
    gyro_bias0=0.010,
    gyro_bias_rw=2.5e-5,
)

PHONE_MID = ImuErrorModel(
    name="phone_mid",
    rate_hz=200.0,
    accel_noise_density=0.0042,
    accel_bias0=0.075,
    accel_bias_rw=0.0016,
    gyro_noise_density=3.4e-4,
    gyro_bias0=0.017,
    gyro_bias_rw=5.0e-5,
)

PHONE_BUDGET = ImuErrorModel(
    name="phone_budget",
    rate_hz=100.0,
    accel_noise_density=0.0080,
    accel_bias0=0.130,
    accel_bias_rw=0.0032,
    gyro_noise_density=6.5e-4,
    gyro_bias0=0.030,
    gyro_bias_rw=1.1e-4,
    has_baro=False,
)

# The IO-VNBD `S-` case: a 10 Hz stream. Tier C -- SVO is not merely degraded
# here, it is unavailable, and the dataset can neither validate nor refute it
# (docs/08-evaluation.md 8.9 threat 2).
PHONE_THROTTLED = ImuErrorModel(
    name="phone_throttled",
    rate_hz=10.0,
    accel_noise_density=0.0080,
    accel_bias0=0.130,
    accel_bias_rw=0.0032,
    gyro_noise_density=6.5e-4,
    gyro_bias0=0.030,
    gyro_bias_rw=1.1e-4,
)

ADIS16505 = ImuErrorModel(
    name="adis16505",
    rate_hz=200.0,
    accel_noise_density=0.00023,
    accel_bias0=0.0030,
    accel_bias_rw=3.0e-5,
    gyro_noise_density=4.2e-5,
    gyro_bias0=0.0012,
    gyro_bias_rw=1.5e-6,
    accel_scale_ppm=500.0,
    gyro_scale_ppm=200.0,
)

FOG = ImuErrorModel(
    name="fog",
    rate_hz=1000.0,
    accel_noise_density=0.00012,
    accel_bias0=0.0015,
    accel_bias_rw=1.0e-5,
    gyro_noise_density=1.5e-6,
    gyro_bias0=2.4e-7,  # 0.05 deg/hr
    gyro_bias_rw=5.0e-9,
    accel_scale_ppm=200.0,
    gyro_scale_ppm=50.0,
)

DEVICES: dict[str, ImuErrorModel] = {
    d.name: d
    for d in (PHONE_FLAGSHIP, PHONE_MID, PHONE_BUDGET, PHONE_THROTTLED, ADIS16505, FOG)
}


@dataclass(frozen=True)
class GnssErrorModel:
    """GNSS quality. Doppler velocity is far better than position, always."""

    name: str
    pos_sigma_m: float
    vel_sigma_mps: float
    n_sats: int
    rate_hz: float = 1.0


GNSS_OPEN_SKY = GnssErrorModel(name="open_sky", pos_sigma_m=2.5, vel_sigma_mps=0.05, n_sats=12)
GNSS_URBAN = GnssErrorModel(name="urban", pos_sigma_m=9.0, vel_sigma_mps=0.18, n_sats=6)


@dataclass(frozen=True)
class MountModel:
    """How the phone sits in its cradle: the rotation ACE must solve for.

    A windscreen cradle holds the phone close to upright, so its body z axis
    points roughly backwards rather than up. Yaw is the interesting unknown --
    it is the one degree of freedom that gravity cannot resolve.
    """

    roll_deg: float = 4.0
    pitch_deg: float = -68.0
    yaw_deg: float = 25.0

    def rotation(self) -> np.ndarray:
        """Vehicle -> phone body rotation."""
        return so3.from_euler_rpy(
            self.roll_deg * DEG, self.pitch_deg * DEG, self.yaw_deg * DEG
        ).T


@dataclass(frozen=True)
class DriveResult:
    """A simulated drive: what the estimator sees, and what actually happened."""

    log: SensorLog
    truth: GroundTruth
    path: RoadPath
    f_ax_true: np.ndarray  # (N,) true axle frequency on the IMU grid, Hz
    gear_true: np.ndarray  # (N,) gear index on the IMU grid
    mount: MountModel
    accel_bias: np.ndarray  # (3,) the constant part actually applied
    gyro_bias: np.ndarray  # (3,)
    outages: tuple[tuple[float, float], ...]

    @property
    def tier(self) -> str:
        return self.log.tier


def _decimate_stages(x: np.ndarray, q: int) -> np.ndarray:
    """Anti-aliased decimation by ``q``, in stages when ``q`` is large.

    A single 100:1 FIR stage is numerically poor; scipy's own guidance is to
    cascade. Zero-phase filtering keeps the IMU aligned with the truth in time,
    which matters because a group delay would appear to the estimator as a
    genuine lag between motion and measurement.
    """
    if q <= 1:
        return x
    out = x
    remaining = q
    for factor in (10, 8, 5, 4, 3, 2):
        while remaining % factor == 0 and remaining > 1 and factor <= 10:
            out = decimate(out, factor, ftype="fir", zero_phase=True, axis=0)
            remaining //= factor
    if remaining > 1:
        out = decimate(out, remaining, ftype="fir", zero_phase=True, axis=0)
    return out


def _magnetic_anomaly(path: RoadPath, seed: int) -> np.ndarray:
    """Per-edge magnetic signature, in nav-frame microtesla, indexed by arc length.

    Keyed to the route and its seed rather than to the traversal, so a second
    drive down the same road sees the *same* signature. That repeatability is
    the entire basis of the EFA anchors: the first vehicle through a tunnel
    records the pattern while its position is still good, and later vehicles
    match against it (``docs/03-approach.md`` 3.8).
    """
    rng = np.random.default_rng(seed)
    n = len(path.s)
    raw = rng.normal(size=(n, 3))
    # Structures that produce anomalies -- rebar, rails, lighting, gantries --
    # have metre-to-decametre scale, so the field is smooth but not flat.
    smooth = gaussian_filter1d(raw, sigma=max(6.0 / path.ds, 1.0), axis=0, mode="nearest")
    smooth /= np.std(smooth, axis=0, keepdims=True) + 1e-12
    return smooth * np.array([7.0, 7.0, 11.0])  # uT, stronger vertically


def simulate_drive(
    route: str = "curvy_a_road",
    *,
    route_length_m: float | None = 1500.0,
    vehicle: VehicleModel = CAR,
    device: ImuErrorModel = PHONE_MID,
    road: VibrationModel = ROAD_NORMAL,
    gnss: GnssErrorModel = GNSS_OPEN_SKY,
    grade: GradeFn = flat,
    outages: tuple[tuple[float, float], ...] = (),
    stops: tuple[float, ...] = (),
    mount: MountModel | None = None,
    seed: int = 0,
    mag_rate_hz: float = 50.0,
    baro_rate_hz: float = 10.0,
    anomaly_seed: int | None = None,
) -> DriveResult:
    """Simulate one drive end to end.

    ``outages`` are ``(start_s, end_s)`` windows during which **all** GNSS is
    withheld -- position, velocity and satellite status alike. Withholding
    position only is the flattering mistake called out in
    ``docs/08-evaluation.md`` 8.1: Doppler velocity is the single most useful
    GNSS product, and leaving it in makes any dead-reckoning result look better
    than it is.
    """
    rng = np.random.default_rng(seed)
    mount = mount or MountModel()

    kwargs = {} if route_length_m is None else {"length_m": route_length_m}
    path = build_route(route, **kwargs)

    # Vibration must be synthesised well above the reported rate so that the
    # anti-alias filter has something real to remove.
    internal_rate = device.rate_hz * max(1, int(np.ceil(1000.0 / device.rate_hz)))
    q = int(round(internal_rate / device.rate_hz))

    truth_hi = simulate_truth(
        path, vehicle, rate_hz=internal_rate, grade=grade, stops=stops, rng=rng, route_name=route
    )
    vib, vib_diag = synthesize_vibration(truth_hi.t, truth_hi.v, vehicle, road, rng)

    # -- assemble the ideal phone-frame signal at the internal rate ----------
    r_vp = mount.rotation()  # vehicle -> phone
    accel_v = truth_hi.accel_ideal + vib
    gyro_v = truth_hi.gyro_ideal
    accel_p = accel_v @ r_vp.T
    gyro_p = gyro_v @ r_vp.T

    # -- band-limit, then decimate to the reported rate ---------------------
    accel_s = _decimate_stages(accel_p, q)
    gyro_s = _decimate_stages(gyro_p, q)
    n = min(len(accel_s), len(gyro_s))
    accel_s, gyro_s = accel_s[:n], gyro_s[:n]
    t = truth_hi.t[0] + np.arange(n) / device.rate_hz

    # Truth is sampled, not filtered: it is the truth, and the sensor is what
    # gets band-limited.
    idx = np.clip(np.searchsorted(truth_hi.t, t), 0, len(truth_hi.t) - 1)
    truth = GroundTruth(
        t=t,
        s=truth_hi.s[idx],
        v=truth_hi.v[idx],
        pos_enu=truth_hi.pos_enu[idx],
        vel_enu=truth_hi.vel_enu[idx],
        R_nb=truth_hi.R_nb[idx],
        psi=truth_hi.psi[idx],
        roll=truth_hi.roll[idx],
        kappa=truth_hi.kappa[idx],
        a_long=truth_hi.a_long[idx],
        a_lat=truth_hi.a_lat[idx],
        omega_z=truth_hi.omega_z[idx],
        accel_ideal=truth_hi.accel_ideal[idx],
        gyro_ideal=truth_hi.gyro_ideal[idx],
        vehicle=vehicle.name,
        route=route,
    )

    # -- inertial error model ----------------------------------------------
    dt = 1.0 / device.rate_hz
    sqrt_dt = np.sqrt(dt)

    accel_bias = rng.normal(scale=device.accel_bias0, size=3)
    gyro_bias = rng.normal(scale=device.gyro_bias0, size=3)
    accel_walk = np.cumsum(rng.normal(scale=device.accel_bias_rw * sqrt_dt, size=(n, 3)), axis=0)
    gyro_walk = np.cumsum(rng.normal(scale=device.gyro_bias_rw * sqrt_dt, size=(n, 3)), axis=0)

    accel_scale = 1.0 + rng.normal(scale=device.accel_scale_ppm * 1e-6, size=3)
    gyro_scale = 1.0 + rng.normal(scale=device.gyro_scale_ppm * 1e-6, size=3)

    accel_meas = (
        accel_s * accel_scale
        + accel_bias
        + accel_walk
        + rng.normal(scale=device.accel_noise_density / sqrt_dt, size=(n, 3))
    )
    gyro_meas = (
        gyro_s * gyro_scale
        + gyro_bias
        + gyro_walk
        + rng.normal(scale=device.gyro_noise_density / sqrt_dt, size=(n, 3))
    )
    imu = ImuStream(t=t, accel=accel_meas, gyro=gyro_meas)

    # -- GNSS ---------------------------------------------------------------
    gnss_t = np.arange(t[0], t[-1], 1.0 / gnss.rate_hz)
    gi = np.clip(np.searchsorted(t, gnss_t), 0, n - 1)
    available = np.ones(len(gnss_t), dtype=bool)
    for start, end in outages:
        available &= ~((gnss_t >= start) & (gnss_t <= end))

    gnss_stream = GnssStream(
        t=gnss_t,
        pos_enu=truth.pos_enu[gi] + rng.normal(scale=gnss.pos_sigma_m, size=(len(gnss_t), 3)),
        vel_enu=truth.vel_enu[gi] + rng.normal(scale=gnss.vel_sigma_mps, size=(len(gnss_t), 3)),
        pos_sigma=np.full(len(gnss_t), gnss.pos_sigma_m),
        vel_sigma=np.full(len(gnss_t), gnss.vel_sigma_mps),
        available=available,
        n_sats=np.where(available, gnss.n_sats, 0),
    )

    # -- barometer ----------------------------------------------------------
    baro = None
    if device.has_baro:
        baro_t = np.arange(t[0], t[-1], 1.0 / baro_rate_hz)
        bi = np.clip(np.searchsorted(t, baro_t), 0, n - 1)
        h = truth.pos_enu[bi, 2]
        pressure = P0_PA * (1.0 - 2.25577e-5 * h) ** 5.25588
        # ~3 Pa RMS is about 0.25 m -- an order below a 3 m parking level.
        pressure = pressure + rng.normal(scale=3.0, size=len(baro_t)) + rng.normal(scale=8.0)
        baro = BaroStream(t=baro_t, pressure_pa=pressure)

    # -- magnetometer -------------------------------------------------------
    mag_t = np.arange(t[0], t[-1], 1.0 / mag_rate_hz)
    mi = np.clip(np.searchsorted(t, mag_t), 0, n - 1)
    anomaly = _magnetic_anomaly(path, seed if anomaly_seed is None else anomaly_seed)
    # Earth field for northern India: ~47 uT total, ~45 degrees inclination.
    earth = np.array([0.0, 33.0, -33.0])
    field_nav = earth + np.stack(
        [np.interp(truth.s[mi], path.s, anomaly[:, k]) for k in range(3)], axis=1
    )
    field_body = np.einsum("nji,nj->ni", truth.R_nb[mi], field_nav) @ r_vp.T
    field_body += rng.normal(scale=0.6, size=field_body.shape)
    mag = MagStream(t=mag_t, field_ut=field_body)

    return DriveResult(
        log=SensorLog(
            imu=imu, gnss=gnss_stream, baro=baro, mag=mag, source=f"sim:{route}:{device.name}"
        ),
        truth=truth,
        path=path,
        f_ax_true=vib_diag["f_ax"][idx],
        gear_true=vib_diag["gear"][idx],
        mount=mount,
        accel_bias=accel_bias,
        gyro_bias=gyro_bias,
        outages=outages,
    )
