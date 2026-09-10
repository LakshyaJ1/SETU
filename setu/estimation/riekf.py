"""IAF -- the right-invariant EKF on SE_2(3) with bias and scale states.

Why right-invariant rather than a quaternion EKF: strapdown IMU dynamics are
*group-affine* on SE_2(3), so the right-invariant error ``eta = X_hat X^-1``
propagates with a Jacobian that does not depend on the estimated state. The
attitude block of that Jacobian is exactly zero, which is the log-linear
property -- and it is why the filter converges from a large initial attitude
error instead of merely tolerating a small one. SETU cold-starts with an
unknown phone mount, so that is the operating condition, not an edge case
(``docs/03-approach.md`` 3.7).

The state is 16-dimensional::

    xi = [ phi(3)   attitude error
           nu(3)    velocity error
           rho(3)   position error
           b_g(3)   gyro bias
           b_a(3)   accelerometer bias
           k(1)  ]  spectral odometer scale, 2 pi R_eff

``k`` is in the state because the calibration cascade is the core of the design:
CTS observes speed absolutely in turns, which calibrates ``k``, and the
calibrated SVO then carries the straights. A constant compiled into the code
could not do that.

Body-frame velocity measurements are especially clean in this formulation. To
first order the attitude error cancels out of ``R^T v``, leaving
``H = [0, R^T, 0, 0, 0]`` -- so the non-holonomic constraint and every speed
channel are exact linear observations of the velocity block, with no attitude
coupling to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core import se23, so3
from ..core.constants import G0

__all__ = ["FilterConfig", "FilterState", "UpdateReport", "InvariantEkf", "IDX"]

# Tangent-space layout. Named so that no Jacobian indexes by magic number.
IDX = {
    "phi": slice(0, 3),
    "nu": slice(3, 6),
    "rho": slice(6, 9),
    "bg": slice(9, 12),
    "ba": slice(12, 15),
    "k": slice(15, 16),
}
DIM = 16
GRAVITY_N = np.array([0.0, 0.0, -G0])


@dataclass(frozen=True)
class FilterConfig:
    """Process noise and gating.

    Noise densities are per root hertz, so the discrete covariance scales with
    ``dt`` and the filter behaves consistently across capability tiers rather
    than needing a retune per device.
    """

    gyro_noise: float = 3.4e-4  # rad/s/sqrt(Hz)
    accel_noise: float = 4.2e-3  # m/s^2/sqrt(Hz)
    gyro_bias_rw: float = 5.0e-5  # rad/s/sqrt(s)
    accel_bias_rw: float = 1.6e-3  # m/s^2/sqrt(s)
    # k drifts with tyre pressure and load -- minutes to days, not seconds.
    k_rw: float = 2.0e-5  # m/rev/sqrt(s)
    chi2_gate: float = 16.0  # per-dimension innovation gate
    min_k: float = 0.5
    max_k: float = 6.0


@dataclass
class FilterState:
    """Mean and covariance of the 16-state filter."""

    X: se23.ExtendedPose = field(default_factory=se23.ExtendedPose)
    b_g: np.ndarray = field(default_factory=lambda: np.zeros(3))
    b_a: np.ndarray = field(default_factory=lambda: np.zeros(3))
    k_svo: float = 1.7467  # 2 pi * 0.278 m, the empirical IO-VNBD radius
    P: np.ndarray = field(default_factory=lambda: np.eye(DIM))
    t: float = 0.0

    def copy(self) -> FilterState:
        return FilterState(
            X=self.X.copy(),
            b_g=self.b_g.copy(),
            b_a=self.b_a.copy(),
            k_svo=self.k_svo,
            P=self.P.copy(),
            t=self.t,
        )

    @property
    def position(self) -> np.ndarray:
        return self.X.p

    @property
    def velocity(self) -> np.ndarray:
        return self.X.v

    @property
    def heading(self) -> float:
        """Yaw of the body x axis in the navigation frame, radians."""
        fwd = self.X.R[:, 0]
        return float(np.arctan2(fwd[1], fwd[0]))

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.X.v))

    @property
    def body_speed(self) -> float:
        """Forward speed: the along-track component, which is what NVE observes."""
        return float(self.X.R[:, 0] @ self.X.v)

    def position_sigma(self) -> float:
        """Horizontal 1-sigma, in metres."""
        return float(np.sqrt(max(self.P[6, 6] + self.P[7, 7], 0.0)))


@dataclass(frozen=True)
class UpdateReport:
    """Outcome of one measurement update -- kept for diagnostics and gating stats."""

    kind: str
    accepted: bool
    nis: float  # normalised innovation squared
    innovation: np.ndarray


class InvariantEkf:
    """Right-invariant EKF with IMU propagation and pluggable measurements."""

    def __init__(self, state: FilterState | None = None, config: FilterConfig | None = None):
        self.s = state or FilterState()
        self.cfg = config or FilterConfig()
        self.reports: list[UpdateReport] = []
        self._prev_accel: np.ndarray | None = None
        self._prev_gyro: np.ndarray | None = None

    # ------------------------------------------------------------ propagate
    def propagate(self, accel: np.ndarray, gyro: np.ndarray, dt: float,
                  q_scale: float = 1.0) -> None:
        """One strapdown step with the right-invariant covariance propagation.

        ``accel`` and ``gyro`` are the samples at the **end** of the interval;
        the interval is integrated with the trapezoidal average of this sample
        and the previous one. Using the leading sample alone (plain Euler) costs
        0.6 m over 85 s on a noiseless IMU -- a tenth of the whole error budget
        in docs/03-approach.md 3.10, spent on arithmetic rather than on physics.

        ``q_scale`` is the hook for the learned adaptive process noise of
        ``docs/03-approach.md`` 3.7: a smooth motorway and a pothole-ridden
        district road should not share one Q. Here it is an explicit multiplier
        so the plumbing exists and the learned head can be dropped in later.
        """
        if dt <= 0:
            return
        s, cfg = self.s, self.cfg
        accel = np.asarray(accel, dtype=float)
        gyro = np.asarray(gyro, dtype=float)
        accel_mid = accel if self._prev_accel is None else 0.5 * (accel + self._prev_accel)
        gyro_mid = gyro if self._prev_gyro is None else 0.5 * (gyro + self._prev_gyro)
        self._prev_accel, self._prev_gyro = accel, gyro

        w = gyro_mid - s.b_g
        a = accel_mid - s.b_a

        R, v, p = s.X.R, s.X.v, s.X.p
        rotation_mid = R @ so3.exp(w * (0.5 * dt))
        acc_n = rotation_mid @ a + GRAVITY_N

        # -- mean: standard strapdown, exact on the manifold ---------------
        R_new = so3.normalize(R @ so3.exp(w * dt))
        v_new = v + acc_n * dt
        p_new = p + v * dt + 0.5 * acc_n * dt * dt

        # -- covariance: the log-linear error dynamics ---------------------
        # The attitude row is zero: attitude error is invariant under the
        # dynamics in these coordinates. That is the whole reason for the
        # right-invariant formulation.
        A = np.zeros((DIM, DIM))
        A[IDX["nu"], IDX["phi"]] = so3.hat(GRAVITY_N)
        A[IDX["rho"], IDX["nu"]] = np.eye(3)
        A[IDX["phi"], IDX["bg"]] = -R
        A[IDX["nu"], IDX["bg"]] = -so3.hat(v) @ R
        A[IDX["nu"], IDX["ba"]] = -R
        A[IDX["rho"], IDX["bg"]] = -so3.hat(p) @ R

        Phi = np.eye(DIM) + A * dt + 0.5 * (A @ A) * dt * dt

        Q = np.zeros((DIM, DIM))
        gn = (cfg.gyro_noise**2) * dt * q_scale
        an = (cfg.accel_noise**2) * dt * q_scale
        Q[IDX["phi"], IDX["phi"]] = gn * (R @ R.T)
        Q[IDX["nu"], IDX["nu"]] = an * (R @ R.T) + gn * (so3.hat(v) @ so3.hat(v).T)
        Q[IDX["rho"], IDX["rho"]] = gn * (so3.hat(p) @ so3.hat(p).T) + 1e-12 * np.eye(3)
        Q[IDX["bg"], IDX["bg"]] = (cfg.gyro_bias_rw**2) * dt * np.eye(3)
        Q[IDX["ba"], IDX["ba"]] = (cfg.accel_bias_rw**2) * dt * np.eye(3)
        Q[IDX["k"], IDX["k"]] = (cfg.k_rw**2) * dt

        s.X = se23.ExtendedPose(R_new, v_new, p_new)
        s.P = Phi @ s.P @ Phi.T + Q
        s.P = 0.5 * (s.P + s.P.T)  # keep it symmetric against float drift
        s.t += dt

    # --------------------------------------------------------------- update
    def _apply(self, kind: str, h_resid: np.ndarray, H: np.ndarray, R_cov: np.ndarray,
               gate: bool = True) -> UpdateReport:
        """Shared Kalman update with a chi-square gate."""
        s = self.s
        S = H @ s.P @ H.T + R_cov
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:  # pragma: no cover - defensive
            return self._record(UpdateReport(kind, False, np.inf, h_resid))

        nis = float(h_resid @ S_inv @ h_resid)
        if gate and nis > self.cfg.chi2_gate * len(h_resid):
            return self._record(UpdateReport(kind, False, nis, h_resid))

        K = s.P @ H.T @ S_inv
        dx = K @ h_resid

        # Retract onto the manifold: the pose correction acts on the *left*,
        # which is what "right-invariant error" means. Applying it additively
        # would leave the attitude off SO(3) and discard the very structure the
        # formulation exists to exploit.
        s.X = s.X.boxplus_left(dx[:9]).normalized()
        s.b_g = s.b_g + dx[IDX["bg"]]
        s.b_a = s.b_a + dx[IDX["ba"]]
        s.k_svo = float(np.clip(s.k_svo + dx[15], self.cfg.min_k, self.cfg.max_k))

        I_KH = np.eye(DIM) - K @ H
        s.P = I_KH @ s.P @ I_KH.T + K @ R_cov @ K.T  # Joseph form: stays positive
        s.P = 0.5 * (s.P + s.P.T)
        return self._record(UpdateReport(kind, True, nis, h_resid))

    def _record(self, report: UpdateReport) -> UpdateReport:
        self.reports.append(report)
        return report

    # -- GNSS ------------------------------------------------------------
    def update_position(self, z: np.ndarray, sigma: float | np.ndarray) -> UpdateReport:
        """Absolute position. ``delta_p = -hat(p) phi + rho`` in these coordinates."""
        s = self.s
        H = np.zeros((3, DIM))
        H[:, IDX["phi"]] = -so3.hat(s.X.p)
        H[:, IDX["rho"]] = np.eye(3)
        R_cov = np.diag(np.broadcast_to(np.asarray(sigma, dtype=float) ** 2, (3,)).copy())
        return self._apply("gnss_pos", np.asarray(z, dtype=float) - s.X.p, H, R_cov)

    def update_velocity(self, z: np.ndarray, sigma: float | np.ndarray) -> UpdateReport:
        """Navigation-frame velocity, e.g. GNSS Doppler.

        Doppler survives with three or four satellites where a position fix does
        not, which is the graceful-degradation path of docs/03-approach.md 3.9.
        """
        s = self.s
        H = np.zeros((3, DIM))
        H[:, IDX["phi"]] = -so3.hat(s.X.v)
        H[:, IDX["nu"]] = np.eye(3)
        R_cov = np.diag(np.broadcast_to(np.asarray(sigma, dtype=float) ** 2, (3,)).copy())
        return self._apply("gnss_vel", np.asarray(z, dtype=float) - s.X.v, H, R_cov)

    # -- body-frame velocity channels ------------------------------------
    def _body_velocity_jacobian(self) -> np.ndarray:
        """``d(R^T v) / d xi``. The attitude error cancels to first order."""
        H = np.zeros((3, DIM))
        H[:, IDX["nu"]] = self.s.X.R.T
        return H

    def update_forward_speed(self, z: float, sigma: float) -> UpdateReport:
        """Along-track speed, from the fused NVE channels."""
        H = self._body_velocity_jacobian()[0:1]
        resid = np.array([float(z) - self.s.body_speed])
        return self._apply("speed", resid, H, np.array([[float(sigma) ** 2]]))

    def update_nhc(self, sigma: float = 0.08) -> UpdateReport:
        """Non-holonomic constraint: no side-slip, no vertical motion in body frame.

        Cheap, continuously available, and the reason a well-tuned INS+NHC
        baseline is the one that must be beaten (``docs/08-evaluation.md`` 8.4,
        baseline B2) rather than a naive strapdown.
        """
        v_body = self.s.X.R.T @ self.s.X.v
        H = self._body_velocity_jacobian()[1:3]
        return self._apply("nhc", -v_body[1:3], H, np.eye(2) * sigma**2)

    def update_zupt(self, sigma: float = 0.02) -> UpdateReport:
        """Zero velocity while stationary -- all three body components."""
        v_body = self.s.X.R.T @ self.s.X.v
        return self._apply(
            "zupt", -v_body, self._body_velocity_jacobian(), np.eye(3) * sigma**2
        )

    def update_svo_frequency(self, f0: float, sigma_f0: float) -> UpdateReport:
        """Axle frequency, which observes speed **and** the scale ``k`` jointly.

        Modelled as ``f0 = v_forward / k`` rather than converting the frequency
        to a speed outside the filter. That is what makes ``k`` observable: with
        an independent speed channel present, the two together identify the
        scale, and this is the mechanism by which a turn calibrates the odometer.
        """
        s = self.s
        k = max(s.k_svo, 1e-6)
        v_fwd = s.body_speed
        H = self._body_velocity_jacobian()[0:1] / k
        H[0, 15] = -v_fwd / (k * k)
        resid = np.array([float(f0) - v_fwd / k])
        return self._apply("svo_f0", resid, H, np.array([[float(sigma_f0) ** 2]]))

    # -- map channels ----------------------------------------------------
    def update_position_2d(self, z_xy: np.ndarray, sigma: float | np.ndarray) -> UpdateReport:
        """Horizontal position only -- what a map snap provides."""
        s = self.s
        H = np.zeros((2, DIM))
        H[:, IDX["phi"]] = -so3.hat(s.X.p)[0:2]
        H[:, IDX["rho"]] = np.eye(3)[0:2]
        R_cov = np.diag(np.broadcast_to(np.asarray(sigma, dtype=float) ** 2, (2,)).copy())
        return self._apply("map_pos", np.asarray(z_xy, dtype=float) - s.X.p[:2], H, R_cov)

    def update_altitude(self, z: float, sigma: float) -> UpdateReport:
        """Barometric altitude."""
        s = self.s
        H = np.zeros((1, DIM))
        H[:, IDX["phi"]] = -so3.hat(s.X.p)[2]
        H[0, 8] = 1.0
        resid = np.array([float(z) - s.X.p[2]])
        return self._apply("baro", resid, H, np.array([[float(sigma) ** 2]]))

    # -- initialisation --------------------------------------------------
    @staticmethod
    def initialise(
        position: np.ndarray,
        velocity: np.ndarray,
        R_nb: np.ndarray,
        *,
        k_svo: float = 1.7467,
        sigma_attitude: float = 0.05,
        sigma_velocity: float = 0.5,
        sigma_position: float = 5.0,
        sigma_bg: float = 0.02,
        sigma_ba: float = 0.10,
        sigma_k: float = 0.05,
        config: FilterConfig | None = None,
    ) -> InvariantEkf:
        """Build a filter with a diagonal prior.

        ``sigma_k`` of 0.05 m/rev is about 3 % of ``k`` -- roughly the spread
        between a tyre's label radius and its actual rolling radius, which is
        the honest starting uncertainty when nothing has calibrated it yet.
        """
        P = np.zeros((DIM, DIM))
        P[IDX["phi"], IDX["phi"]] = np.eye(3) * sigma_attitude**2
        P[IDX["nu"], IDX["nu"]] = np.eye(3) * sigma_velocity**2
        P[IDX["rho"], IDX["rho"]] = np.eye(3) * sigma_position**2
        P[IDX["bg"], IDX["bg"]] = np.eye(3) * sigma_bg**2
        P[IDX["ba"], IDX["ba"]] = np.eye(3) * sigma_ba**2
        P[15, 15] = sigma_k**2
        state = FilterState(
            X=se23.ExtendedPose(so3.normalize(R_nb), velocity, position),
            k_svo=k_svo,
            P=P,
        )
        return InvariantEkf(state, config)

    # -- diagnostics -----------------------------------------------------
    def gating_stats(self) -> dict[str, tuple[int, int]]:
        """``{kind: (accepted, total)}`` -- a rejection spike is a real signal."""
        out: dict[str, list[int]] = {}
        for r in self.reports:
            entry = out.setdefault(r.kind, [0, 0])
            entry[0] += int(r.accepted)
            entry[1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}
