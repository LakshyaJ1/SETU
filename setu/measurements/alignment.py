"""ACE -- the Alignment and Calibration Engine.

The phone sits in a cradle at an unknown orientation, and every body-frame
relation in the system -- the non-holonomic constraint, CTS, the forward-speed
update -- is stated in *vehicle* axes. So the phone-to-vehicle rotation has to
be recovered before any of them mean anything.

Two of its three degrees of freedom are easy: gravity fixes roll and pitch.
The third, mount yaw, is the interesting one, and ``docs/03-approach.md`` 3.9
gives the trick that solves it **without GNSS**: during any turn the horizontal
specific-force axis that correlates with yaw rate *is* the lateral axis, because
``a_lat = v * Omega``. The orthogonal axis is forward, and its sign is fixed by
requiring the vehicle to move forwards rather than backwards.

That matters because it means alignment can converge inside a tunnel, on a
vehicle that entered with the phone already re-seated -- the case where a
GNSS-course-over-ground method has nothing to work with.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core import so3
from ..sensors.types import GnssStream, ImuStream

__all__ = ["AlignmentResult", "estimate_mount"]


def _speed_at(t: np.ndarray, gnss: GnssStream | None) -> np.ndarray | None:
    """Horizontal speed on the given epochs, from available GNSS only.

    Returns ``None`` when GNSS cannot cover the window, which is what puts
    :func:`estimate_mount` onto its unaided fallback rather than letting it
    interpolate across a blackout and pretend it had speed all along.
    """
    if gnss is None or len(gnss) < 3:
        return None
    ok = gnss.available
    if int(ok.sum()) < 3:
        return None
    t_g = gnss.t[ok]
    speed = np.linalg.norm(gnss.vel_enu[ok][:, :2], axis=1)
    # Refuse to extrapolate: if the requested window reaches outside the fixes
    # by more than a couple of epochs, the speed there is not known.
    margin = 2.0 * float(np.median(np.diff(t_g))) if len(t_g) > 1 else 1.0
    if t.min() < t_g[0] - margin or t.max() > t_g[-1] + margin:
        return None
    return np.interp(t, t_g, speed)


@dataclass(frozen=True)
class AlignmentResult:
    """Phone-to-vehicle rotation and how much to trust it."""

    R_pv: np.ndarray  # (3, 3) phone -> vehicle
    converged: bool
    sigma_yaw_rad: float
    method: str
    n_turn_samples: int = 0

    def to_vehicle(self, v: np.ndarray) -> np.ndarray:
        """Rotate phone-frame vectors (N, 3) into the vehicle frame."""
        return np.asarray(v, dtype=float) @ self.R_pv.T


def estimate_mount(
    imu: ImuStream,
    *,
    gnss: GnssStream | None = None,
    window_s: float | None = None,
    min_yaw_rate: float = 0.06,
    min_turn_samples: int = 40,
) -> AlignmentResult:
    """Estimate the phone-to-vehicle rotation from a stretch of driving.

    Roll and pitch come from the gravity direction. Yaw comes from the
    correlation between horizontal specific force and yaw rate, which requires
    turns -- so on a dead-straight warm-up the result is reported as
    unconverged rather than guessed at.

    ``gnss``, when available, only disambiguates the *sign* of the forward
    axis. The axis itself is found without it.
    """
    accel = np.asarray(imu.accel, dtype=float)
    gyro = np.asarray(imu.gyro, dtype=float)
    n = len(imu)
    if window_s is not None:
        keep = imu.t <= imu.t[0] + window_s
        accel, gyro, n = accel[keep], gyro[keep], int(keep.sum())
    if n < 20:
        return AlignmentResult(np.eye(3), False, np.inf, "too-short")

    # -- roll and pitch: gravity is the vehicle's up axis, on average -------
    g_dir = accel.mean(axis=0)
    norm = np.linalg.norm(g_dir)
    if norm < 1e-6:
        return AlignmentResult(np.eye(3), False, np.inf, "no-gravity")
    z_v = g_dir / norm  # vehicle "up", expressed in phone axes

    # -- yaw: the horizontal axis that tracks yaw rate is the lateral one ----
    # Project out gravity, leaving horizontal specific force in phone axes.
    a_h = accel - np.outer(accel @ z_v, z_v)
    omega_vert = gyro @ z_v  # yaw rate about the vehicle vertical

    turning = np.abs(omega_vert) > min_yaw_rate
    n_turn = int(turning.sum())
    if n_turn < min_turn_samples:
        return AlignmentResult(np.eye(3), False, np.inf, "no-turns", n_turn)

    # Build an arbitrary horizontal basis, then solve for the angle within it.
    seed = np.array([1.0, 0.0, 0.0])
    if abs(seed @ z_v) > 0.9:
        seed = np.array([0.0, 1.0, 0.0])
    e1 = seed - (seed @ z_v) * z_v
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(z_v, e1)

    # a_lat = v * Omega, so the component along the true lateral axis is the one
    # proportional to Omega.
    #
    # A plain regression of horizontal force on Omega is biased, and roundabouts
    # are where it shows: drivers brake going in and accelerate coming out, so
    # longitudinal acceleration is *correlated* with yaw rate and leaks into the
    # estimate. Measured on the simulator that bias is ~8 degrees of mount yaw,
    # against ~1 degree on an A-road.
    #
    # The bias cannot be removed by treating the longitudinal signal as a
    # nuisance regressor derived from the current estimate -- that projection is
    # circular and leaves the direction an immediate fixed point. It needs an
    # independent handle, and speed is one: with v known, the lateral
    # acceleration is a *predicted* signal l = v * Omega, and the problem
    # collapses to a single angle.
    #
    #     find theta minimising  || yhat(theta) . a_h  -  l ||^2
    #
    # The orthogonal component is left free, so it absorbs whatever the
    # longitudinal acceleration was doing and stops biasing the answer.
    w = omega_vert[turning]
    a1 = a_h[turning] @ e1
    a2 = a_h[turning] @ e2
    if float(w @ w) < 1e-12:
        return AlignmentResult(np.eye(3), False, np.inf, "degenerate", n_turn)

    # Only the *direction* of the fit may be constrained, never its magnitude.
    # The measured lateral force is not v * Omega: body roll leaks gravity into
    # that channel at g * sin(roll), a ~12 % discrepancy on a car rolling a
    # degree or two. A cost that also matches magnitude makes the angle absorb
    # that error -- tried, and it turned a 0.8 degree estimate into 12.6.
    #
    # The residual bias is the longitudinal acceleration that correlates with
    # yaw rate. It is removed by *excluding samples*, not by reprojecting them:
    # after a first pass the forward axis is known well enough to spot the
    # brake-in/accelerate-out epochs, and steady-state cornering -- where
    # a_fwd is genuinely near zero -- is what remains.
    keep = np.ones(n_turn, dtype=bool)
    c1 = c2 = 0.0
    for _ in range(4):
        ww = float(w[keep] @ w[keep])
        if ww < 1e-12 or keep.sum() < min_turn_samples:
            break
        c1 = float(a1[keep] @ w[keep] / ww)
        c2 = float(a2[keep] @ w[keep] / ww)
        norm_c = np.hypot(c1, c2)
        if norm_c < 1e-12:
            break
        lat_dir = np.array([c1, c2]) / norm_c
        fwd_dir = np.array([-lat_dir[1], lat_dir[0]])
        a_fwd = fwd_dir[0] * a1 + fwd_dir[1] * a2
        cut = np.quantile(np.abs(a_fwd), 0.6)
        new_keep = np.abs(a_fwd) <= cut
        if new_keep.sum() < min_turn_samples:
            break
        keep = new_keep

    if abs(c1) + abs(c2) < 1e-12:
        return AlignmentResult(np.eye(3), False, np.inf, "degenerate", n_turn)
    method = "turn-correlation"
    # Strength: how much of the retained lateral signal the yaw rate explains.
    lat_sig = (c1 * a1[keep] + c2 * a2[keep]) / max(np.hypot(c1, c2), 1e-12)
    resid = lat_sig - np.hypot(c1, c2) * w[keep] / max(np.hypot(c1, c2), 1e-12)
    strength = float(np.std(lat_sig) / (np.std(resid) + 1e-9))

    y_v = c1 * e1 + c2 * e2  # points along +lateral (left), up to sign
    y_v /= np.linalg.norm(y_v)
    x_v = np.cross(y_v, z_v)  # forward = left x up, right-handed
    x_v /= np.linalg.norm(x_v)

    # -- sign of forward ----------------------------------------------------
    # The fit above pins the lateral *axis* but not its direction, and a 180
    # degree error is the difference between driving forwards and backwards.
    # The speed-aided form resolves it for free: a sign flip would make the
    # residual against l = v * Omega much worse, so the minimiser already
    # chose correctly. The correlation form does not, so it needs this check.
    flip = False
    if method == "turn-correlation" and gnss is not None and len(gnss) > 2:
        ok = gnss.available
        if ok.sum() > 2:
            speed = np.linalg.norm(gnss.vel_enu[ok][:, :2], axis=1)
            if len(speed) > 2:
                dv = np.gradient(speed, gnss.t[ok])
                a_fwd = np.interp(gnss.t[ok], imu.t[:n], a_h @ x_v)
                if float(np.dot(dv, a_fwd)) < 0:
                    flip = True
                method = "turn-correlation+gnss-sign"
    if flip:
        x_v, y_v = -x_v, -y_v

    # Rows are the vehicle axes expressed in phone coordinates, so this maps a
    # phone-frame vector into the vehicle frame.
    R_pv = so3.normalize(np.stack([x_v, y_v, z_v], axis=0))

    # Yaw uncertainty from how well the turn signal was actually explained. A
    # weak or noisy turn signal is a weak yaw estimate, and the filter has to
    # know that rather than being handed a confident wrong mount.
    sigma_yaw = float(np.clip(0.35 / max(strength, 1e-3), 0.004, 1.0))
    return AlignmentResult(R_pv, True, sigma_yaw, method, n_turn)
