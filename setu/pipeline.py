"""SMM -- the Seamless Mode Manager: sensors in, trajectory out.

This is the orchestration layer of ``docs/04-architecture.md`` 4.2. It owns the
session lifecycle, decides which measurement generators may speak at each epoch,
and hands their output to the filter. Every module can be switched off through
:class:`PipelineConfig`, which is what makes the ablation matrix of
``docs/08-evaluation.md`` 8.5 a set of config flags rather than a set of code
edits.

The design rule that matters here is the fourth guiding constraint of 4.1:
**graceful degradation, never a cliff**. Every generator publishes a validity
flag and a variance, the filter consumes whatever is valid, and losing a module
costs accuracy rather than stability. Nothing in this file special-cases the
absence of a sensor; a missing channel simply never reports.
"""

from __future__ import annotationsfrom dataclasses import dataclass, fieldimport numpy as npfrom .core import so3from .estimation.riekf import FilterConfig, InvariantEkffrom .mapping.road import RoadPathfrom .measurements.alignment import estimate_mountfrom .measurements.csa import CsaConfig, align_heading_profilefrom .measurements.cts import CtsConfig, levelled_speedfrom .measurements.svo import SpectralOdometer, SvoConfigfrom .measurements.types import ScalarMeasurement, merge_inverse_variancefrom .sensors.types import ImuStream, SensorLog__all__ = ["PipelineConfig", "Solution", "run_pipeline"]


@dataclass(frozen=True)
class PipelineConfig:
    """Which channels are enabled, and how they are tuned.

    Every ``use_*`` flag is an ablation from ``docs/08-evaluation.md`` 8.5.
    Turning one off must degrade the result without destabilising it -- that is
    a property the ablation tests check.
    """

    use_gnss: bool = True
    use_svo: bool = True
    use_cts: bool = True
    use_csa: bool = True
    use_nhc: bool = True
    use_zupt: bool = True

    # Warm-up with full GNSS so biases, the mount and k converge before any
    # outage begins. docs/08-evaluation.md 8.1 step 1 specifies at least 120 s,
    # and it is not a round number for the sake of one: mount yaw is estimated
    # from turn correlation, and at 30 s there are too few bends. Measured, the
    # mount error was 49.9 deg at a 30 s window against 2.1 deg at 120 s.
    warmup_s: float = 120.0
    output_rate_hz: float = 10.0

    nhc_sigma: float = 0.15
    nhc_min_speed: float = 1.5
    zupt_speed_threshold: float = 0.4
    zupt_sigma: float = 0.02

    speed_update_hz: float = 10.0
    csa_period_s: float = 5.0
    csa_window_s: float = 30.0
    cross_track_sigma_m: float = 1.8  # lane half-width

    svo: SvoConfig = field(default_factory=SvoConfig)
    cts: CtsConfig = field(default_factory=CtsConfig)
    csa: CsaConfig = field(default_factory=CsaConfig)
    filt: FilterConfig = field(default_factory=FilterConfig)


@dataclass
class Solution:
    """The estimated trajectory, sampled at the output rate."""

    t: np.ndarray
    pos_enu: np.ndarray  # (N, 3)
    vel_enu: np.ndarray  # (N, 3)
    heading: np.ndarray  # (N,)
    speed: np.ndarray  # (N,)
    sigma_pos: np.ndarray  # (N,) horizontal 1-sigma
    gnss_available: np.ndarray  # (N,) bool -- False means dead reckoning
    k_svo: np.ndarray  # (N,) the scale state, to watch it calibrate
    anchors: list[tuple[float, float, str]] = field(default_factory=list)
    # Per-channel availability, {name: (t, valid)}. The gaps are diagnostic:
    # docs/03-approach.md 3.11 claims no two channels share a blind spot, and
    # this is the record that either shows that or does not.
    channels: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    tier: str = "?"
    gating: dict[str, tuple[int, int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.t)


def _initial_attitude(
    log: SensorLog, cfg: PipelineConfig
) -> tuple[np.ndarray, np.ndarray, float, list[str]]:
    """Initial vehicle attitude and the phone-to-vehicle mount rotation.

    Built from two directions that are both observable during a GNSS warm-up:
    the vehicle's up axis, from measured gravity, and its forward axis, from
    ACE's turn correlation. Composing them with the GNSS course over ground
    gives the phone's attitude in the navigation frame without ever assuming the
    phone is mounted any particular way.
    """
    notes: list[str] = []
    warm = log.imu.t <= log.imu.t[0] + cfg.warmup_s
    align = estimate_mount(log.imu, gnss=log.gnss, window_s=cfg.warmup_s)

    if align.converged:
        R_pv = align.R_pv  # phone -> vehicle
        sigma_att = float(np.clip(align.sigma_yaw_rad, 0.02, 0.6))
        notes.append(f"mount: {align.method}, sigma_yaw {np.degrees(align.sigma_yaw_rad):.1f} deg")
    else:
        # No turns in the warm-up, so mount yaw is unobservable. Fall back to
        # gravity for roll/pitch and let GNSS velocity fix the heading; the
        # filter will absorb the residual yaw error as attitude error.
        g_dir = log.imu.accel[warm].mean(axis=0)
        z_v = g_dir / np.linalg.norm(g_dir)
        seed = np.array([1.0, 0.0, 0.0])
        if abs(seed @ z_v) > 0.9:
            seed = np.array([0.0, 1.0, 0.0])
        x_v = seed - (seed @ z_v) * z_v
        x_v /= np.linalg.norm(x_v)
        R_pv = so3.normalize(np.stack([x_v, np.cross(z_v, x_v), z_v], axis=0))
        # Mount yaw is entirely unknown here, so the prior must say so. A
        # confident prior on an unknown angle is what makes an EKF gate out the
        # very measurements that would have corrected it.
        sigma_att = 1.2
        notes.append(f"mount: unconverged ({align.method}); yaw left to the filter")

    # Vehicle heading at t0, from GNSS course over ground.
    #
    # From the *earliest* usable fixes, not averaged over the warm-up. On a
    # winding road the vehicle turns through tens of degrees during the warm-up,
    # so a mean heading over that window describes no instant of the drive: it
    # put 19 deg of yaw error into the initial attitude and the filter then
    # gated out the measurements that would have removed it.
    psi0 = 0.0
    ok = log.gnss.available & (log.gnss.t <= log.gnss.t[0] + cfg.warmup_s)
    if ok.sum() >= 2:
        v = log.gnss.vel_enu[ok]
        fast = np.linalg.norm(v[:, :2], axis=1) > 2.0
        if fast.any():
            first = v[fast][:3, :2].mean(axis=0)  # first few epochs only
            psi0 = float(np.arctan2(first[1], first[0]))

    R_nv = so3.from_euler_rpy(0.0, 0.0, psi0)  # vehicle -> nav
    return so3.normalize(R_nv), so3.normalize(R_pv), sigma_att, notes


def run_pipeline(
    log: SensorLog,
    *,
    path: RoadPath | None = None,
    config: PipelineConfig | None = None,
) -> Solution:
    """Run the estimator over a sensor log.

    ``path`` is the offline map. Without it CSA and the cross-track constraint
    are unavailable and the system degrades to inertial plus whatever speed
    channels the device supports -- which is a supported mode, not an error.
    """
    cfg = config or PipelineConfig()
    n = len(log.imu)
    if n < 10:
        raise ValueError("sensor log too short to process")
    rate = log.imu.rate_hz
    dt = 1.0 / rate
    notes: list[str] = []

    # ---------------------------------------------------------- initialise
    R_nv0, R_pv, sigma_att0, init_notes = _initial_attitude(log, cfg)
    notes += init_notes

    # Everything downstream works in VEHICLE axes, so the IMU is rotated once,
    # here, and the filter's attitude state is the vehicle's.
    #
    # This is not cosmetic. The non-holonomic constraint says a *vehicle* has no
    # lateral or vertical velocity; applied in the phone frame, with a cradle
    # pitched back 68 degrees, it asserts something false about axes that
    # legitimately carry most of the motion. Measured: NHC was accepted 2999
    # times out of 2999 with vehicle-frame attitude and 0 times out of 5999 with
    # phone-frame attitude, and the filter diverged past 7 km. The same applies
    # to the forward-speed channel, which otherwise projects speed onto a phone
    # axis that is not the direction of travel.
    #
    # The residual mount error is fixed rather than estimated here; carrying
    # psi_bv as a filter state (docs/03-approach.md 3.2) is future work.
    accel_v = log.imu.accel @ R_pv.T
    gyro_v = log.imu.gyro @ R_pv.T
    imu = ImuStream(t=log.imu.t, accel=accel_v, gyro=gyro_v)
    R0 = R_nv0

    ok0 = log.gnss.available
    if cfg.use_gnss and ok0.any():
        p0 = log.gnss.pos_enu[ok0][0]
        v0 = log.gnss.vel_enu[ok0][0]
    else:
        p0 = np.zeros(3)
        v0 = np.zeros(3)
        notes.append("no GNSS at start: initialised at the origin, at rest")

    # The attitude prior is ACE's own uncertainty, not a constant. Starting
    # confident about an unknown mount is what makes the innovation gate lock
    # out every measurement that would have corrected it.
    ekf = InvariantEkf.initialise(
        p0, v0, R0, sigma_attitude=sigma_att0, config=cfg.filt
    )

    # ------------------------------------------------- speed channels, batch
    # SVO and CTS are computed over the whole log up front. They are windowed
    # estimators, so a streaming implementation would carry ring buffers; doing
    # it in one pass here keeps the reference implementation readable, and the
    # result is identical because neither looks into the future beyond its own
    # window.
    speed_sources: list[ScalarMeasurement] = []
    channels: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    tier = log.tier

    if cfg.use_svo:
        svo = SpectralOdometer(k_svo=ekf.s.k_svo, config=cfg.svo).estimate(log.imu)
        if svo.available:
            resampled = svo.speed.resampled_to(imu.t)
            speed_sources.append(resampled)
            channels["SVO - spectral odometer"] = (imu.t, resampled.valid)
            notes.append(f"SVO active, {svo.speed.coverage:.0%} of the whole session")
        else:
            notes.append(f"SVO unavailable: {svo.reason}")

    if cfg.use_cts:
        # CTS needs attitude. The pipeline runs it against a dead-reckoned
        # attitude computed from the gyro alone, which is accurate over the
        # seconds-long window a turn occupies.
        R_track = _integrate_attitude(imu, R0)
        heading = np.arctan2(R_track[:, 1, 0], R_track[:, 0, 0])
        cts = levelled_speed(imu.t, imu.accel, imu.gyro, R_track, heading, config=cfg.cts)
        speed_sources.append(cts)
        channels["CTS - coordinated turn"] = (imu.t, cts.valid)
        notes.append(f"CTS valid for {cts.coverage:.0%} of the whole session")

    fused_speed = (
        merge_inverse_variance([m.resampled_to(imu.t) for m in speed_sources])
        if speed_sources
        else None
    )

    # ------------------------------------------------------------ main loop
    out_stride = max(int(round(rate / cfg.output_rate_hz)), 1)
    speed_stride = max(int(round(rate / cfg.speed_update_hz)), 1)
    csa_stride = max(int(round(rate * cfg.csa_period_s)), 1)
    csa_window = int(round(rate * cfg.csa_window_s))

    gnss_idx = 0
    gnss_t = log.gnss.t
    n_gnss = len(gnss_t)

    out_t, out_p, out_v, out_h, out_s, out_sig, out_ok, out_k = [], [], [], [], [], [], [], []
    anchors: list[tuple[float, float, str]] = []
    csa_t: list[float] = []
    csa_ok: list[bool] = []
    psi_hist = np.zeros(n)
    s_hist = np.zeros(n)

    for i in range(n):
        if i > 0:
            ekf.propagate(imu.accel[i], imu.gyro[i], dt)

        psi_hist[i] = ekf.s.heading
        s_hist[i] = s_hist[i - 1] + max(ekf.s.body_speed, 0.0) * dt if i > 0 else 0.0

        # -- GNSS, when it is there -------------------------------------
        gnss_here = False
        while gnss_idx < n_gnss and gnss_t[gnss_idx] <= imu.t[i]:
            if cfg.use_gnss and log.gnss.available[gnss_idx]:
                ekf.update_position(log.gnss.pos_enu[gnss_idx], log.gnss.pos_sigma[gnss_idx])
                ekf.update_velocity(log.gnss.vel_enu[gnss_idx], log.gnss.vel_sigma[gnss_idx])
                gnss_here = True
            gnss_idx += 1

        # -- kinematic constraints --------------------------------------
        speed_now = ekf.s.body_speed
        if cfg.use_zupt and abs(speed_now) < cfg.zupt_speed_threshold:
            ekf.update_zupt(sigma=cfg.zupt_sigma)
        elif cfg.use_nhc and speed_now > cfg.nhc_min_speed and i % 2 == 0:
            ekf.update_nhc(sigma=cfg.nhc_sigma)

        # -- fused speed -------------------------------------------------
        if fused_speed is not None and i % speed_stride == 0 and fused_speed.valid[i]:
            sigma = float(fused_speed.sigma[i])
            if np.isfinite(sigma) and sigma > 0:
                ekf.update_forward_speed(float(fused_speed.value[i]), sigma)

        # -- curvature registration --------------------------------------
        if (
            cfg.use_csa
            and path is not None
            and i >= csa_window
            and i % csa_stride == 0
            and imu.t[i] > imu.t[0] + cfg.warmup_s
        ):
            lo = i - csa_window
            s_prior, _ = path.project(ekf.s.position[:2])
            fix = align_heading_profile(
                path,
                psi_hist[lo : i + 1],
                s_hist[lo : i + 1],
                s0_prior=max(s_prior - (s_hist[i] - s_hist[lo]), 0.0),
                config=cfg.csa,
            )
            csa_t.append(float(imu.t[i]))
            accepted = False
            if fix.observable and fix.position_xy is not None:
                r = ekf.update_position_2d(fix.position_xy, fix.sigma_s)
                if r.accepted:
                    anchors.append((float(imu.t[i]), float(fix.sigma_s), "csa"))
                    accepted = True
            csa_ok.append(accepted)

        # -- record -------------------------------------------------------
        if i % out_stride == 0:
            out_t.append(imu.t[i])
            out_p.append(ekf.s.position.copy())
            out_v.append(ekf.s.velocity.copy())
            out_h.append(ekf.s.heading)
            out_s.append(ekf.s.body_speed)
            out_sig.append(ekf.s.position_sigma())
            out_ok.append(gnss_here)
            out_k.append(ekf.s.k_svo)

    # GNSS availability at output epochs, from the log rather than from whether
    # an update happened to land on this exact sample.
    out_t_arr = np.asarray(out_t)
    avail = (
        np.interp(out_t_arr, gnss_t, log.gnss.available.astype(float)) > 0.5
        if n_gnss
        else np.zeros(len(out_t_arr), dtype=bool)
    )

    if csa_t:
        channels["CSA - curvature registration"] = (np.asarray(csa_t), np.asarray(csa_ok))
    if n_gnss:
        channels["GNSS"] = (gnss_t, log.gnss.available)

    return Solution(
        t=out_t_arr,
        pos_enu=np.asarray(out_p),
        vel_enu=np.asarray(out_v),
        heading=np.asarray(out_h),
        speed=np.asarray(out_s),
        sigma_pos=np.asarray(out_sig),
        gnss_available=avail,
        k_svo=np.asarray(out_k),
        anchors=anchors,
        channels=channels,
        tier=tier,
        gating=ekf.gating_stats(),
        notes=notes,
    )


def _integrate_attitude(imu, R0: np.ndarray) -> np.ndarray:
    """Gyro-only attitude history, for generators that need a frame up front.

    Free-running and therefore drifting, but CTS only looks across the few
    seconds of a single turn, over which the drift is negligible. The filter's
    own attitude is the one used for anything that accumulates.
    """
    n = len(imu)
    out = np.empty((n, 3, 3))
    R = so3.normalize(R0)
    out[0] = R
    dt = 1.0 / imu.rate_hz
    for i in range(1, n):
        R = R @ so3.exp(0.5 * (imu.gyro[i] + imu.gyro[i - 1]) * dt)
        if i % 200 == 0:
            R = so3.normalize(R)
        out[i] = R
    return out
