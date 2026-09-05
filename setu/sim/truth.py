"""Ground-truth trajectory generation.

Everything here is analytic. Position, velocity and acceleration all come from
one cubic spline in arc length, and attitude, angular rate and specific force
are closed-form functions of the path and the vehicle model. Nothing in the
truth is produced by numerically differentiating something else, because a
truth trajectory whose ``v`` disagrees with its own ``ds/dt`` would silently
reward or punish an estimator for the simulator's inconsistency rather than for
its own accuracy.

The specific force is the important output: it is what makes the whole exercise
a test rather than a demonstration. ``f_b = R^T (a_n + g)`` is written once,
from the kinematics, and CTS then has to *recover* speed from it without ever
being told the answer.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.interpolate import CubicSpline

from ..core.constants import G0
from ..mapping.road import RoadPath
from ..sensors.types import GroundTruth
from .vehicle import VehicleModel, speed_profile

__all__ = ["simulate_truth", "GradeFn", "flat", "tunnel_dip", "parking_ramp"]

GradeFn = Callable[[np.ndarray], np.ndarray]


def flat(s: np.ndarray) -> np.ndarray:
    """No gradient."""
    return np.zeros_like(np.asarray(s, dtype=float))


def tunnel_dip(enter_m: float, exit_m: float, depth_m: float = 18.0) -> GradeFn:
    """Down-then-up profile of an underpass, smooth enough to differentiate.

    The barometer sees this as a pressure signature, which is one of the EFA
    anchors (``docs/03-approach.md`` 3.8) and is also how the tunnel's grade
    profile is matched against the DEM.
    """
    mid = 0.5 * (enter_m + exit_m)
    width = max((exit_m - enter_m) / 4.0, 1.0)

    def grade(s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        # d/ds of a Gaussian well of depth `depth_m`.
        u = (s - mid) / width
        return depth_m * u / width * np.exp(-0.5 * u * u)

    return grade


def parking_ramp(deck_m: float, turn_m: float, rise_per_level_m: float = 3.0) -> GradeFn:
    """Level decks joined by climbing helical ramps.

    Levels 2.8-3.2 m apart are an order of magnitude above MEMS barometer noise,
    which is what makes the level itself essentially always resolvable.
    """
    period = deck_m + turn_m

    def grade(s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        phase = np.mod(s, period)
        on_ramp = phase >= deck_m
        # Smoothed with a raised cosine so the pitch rate stays finite.
        u = np.clip((phase - deck_m) / max(turn_m, 1e-9), 0.0, 1.0)
        shape = 0.5 * (1.0 - np.cos(2.0 * np.pi * u)) * 2.0  # mean 1 over the ramp
        return np.where(on_ramp, rise_per_level_m / turn_m * shape, 0.0)

    return grade


def simulate_truth(
    path: RoadPath,
    vehicle: VehicleModel,
    *,
    rate_hz: float = 200.0,
    grade: GradeFn = flat,
    stops: tuple[float, ...] = (),
    profile_dt: float = 0.02,
    rng: np.random.Generator | None = None,
    route_name: str = "unknown",
) -> GroundTruth:
    """Drive ``vehicle`` along ``path`` and return the exact trajectory.

    ``rate_hz`` is the truth (and IMU) sample rate, which is what selects the
    capability tier: 200 Hz is Tier A, where SVO can see axle harmonics; 10 Hz
    is Tier C, the IO-VNBD ``S-`` case, where it cannot.
    """
    rng = rng or np.random.default_rng(0)

    # -- along-path motion --------------------------------------------------
    # One spline carries the speed; arc length is its antiderivative and
    # acceleration its derivative, so all three are consistent by construction
    # and the speed can never go negative through interpolation overshoot.
    t_coarse, v_coarse = speed_profile(path, vehicle, dt=profile_dt, stops=stops, rng=rng)
    if len(t_coarse) < 4:
        raise ValueError("speed profile too short to spline; check the route length")

    v_spline = CubicSpline(t_coarse, v_coarse, bc_type="natural")
    s_spline = v_spline.antiderivative()

    n = int(np.floor((t_coarse[-1] - t_coarse[0]) * rate_hz)) + 1
    t = t_coarse[0] + np.arange(n) / rate_hz

    s = s_spline(t)
    # End the run where the road ends. Clamping s to the edge length instead
    # would freeze position while speed stayed at 17 m/s, and the truth would
    # then contradict itself: v would no longer be d(pos)/dt.
    past_end = np.flatnonzero(s >= path.length)
    if past_end.size:
        n = max(int(past_end[0]), 8)
        t, s = t[:n], s[:n]
    s = np.clip(s, 0.0, path.length)
    v_h = np.maximum(v_spline(t), 0.0)  # horizontal speed
    a_h = v_spline(t, 1)  # horizontal along-path acceleration

    # -- path geometry at those arc lengths --------------------------------
    # The vehicle drives the C2 spline through the map samples, and *every*
    # geometric quantity is taken from that one spline. Mixing sources here is
    # subtly fatal: linear interpolation of position points up to 0.006 rad off
    # the tangent on a 90 m bend, and the map's stored curvature is not the
    # derivative of its stored heading at a corner, so a truth built from
    # `position_at` plus `curvature_at` disagrees with itself in both position
    # and yaw rate. The polyline is how the map stores the road; it is not the
    # road.
    psi_spline = CubicSpline(path.s, path.psi)
    psi = psi_spline(s)
    kappa = psi_spline(s, 1)
    # Position is the integral of the heading, not a second independent
    # interpolant. Splining xy separately leaves position and velocity
    # disagreeing by ~15 mm/s where the two interpolants ring differently, and
    # integrating the tangent on the simulation grid is also the more accurate
    # of the two: the sub-centimetre step size puts the trapezoid error below a
    # millimetre over a kilometre. test_truth_stays_on_the_road checks that.
    xy0 = CubicSpline(path.s, path.xy, axis=0)(s[0])
    heading_xy = np.stack([np.cos(psi), np.sin(psi)], axis=1)
    ds_step = np.diff(s)
    increments = 0.5 * (heading_xy[1:] + heading_xy[:-1]) * ds_step[:, None]
    xy = xy0 + np.vstack([np.zeros((1, 2)), np.cumsum(increments, axis=0)])

    # -- vertical profile ---------------------------------------------------
    # Altitude is the integral of grade over horizontal arc length; the climb
    # angle and its arc-length derivative follow from the grade directly.
    s_grid = path.s
    g_grid = np.asarray(grade(s_grid), dtype=float)
    z_grid = np.concatenate([[0.0], np.cumsum(0.5 * (g_grid[1:] + g_grid[:-1]) * np.diff(s_grid))])
    z = np.interp(s, s_grid, z_grid)

    grade_s = np.interp(s, s_grid, g_grid)
    th = np.arctan(grade_s)  # climb angle, positive nose-up
    dgrade_ds = np.interp(s, s_grid, np.gradient(g_grid, path.ds))
    dth_ds = dgrade_ds / (1.0 + grade_s**2)

    cth, sth = np.cos(th), np.sin(th)
    cps, sps = np.cos(psi), np.sin(psi)

    # -- three-dimensional kinematics --------------------------------------
    # The wheels roll along the road surface, so the speed SVO would read is the
    # 3-D speed, which exceeds the horizontal speed by 1/cos(climb).
    v3 = v_h / cth
    thdot = dth_ds * v_h
    a3 = (a_h * cth + v_h * sth * thdot) / (cth * cth)

    tangent = np.stack([cth * cps, cth * sps, sth], axis=1)
    dT_ds = np.stack(
        [
            -sth * dth_ds * cps - cth * sps * kappa,
            -sth * dth_ds * sps + cth * cps * kappa,
            cth * dth_ds,
        ],
        axis=1,
    )

    pos = np.column_stack([xy, z])
    vel = v3[:, None] * tangent
    acc = a3[:, None] * tangent + (v3 * v_h)[:, None] * dT_ds

    # -- attitude -----------------------------------------------------------
    a_lat = kappa * v_h * v_h  # horizontal centripetal acceleration
    roll = vehicle.roll_angle(a_lat)
    omega_z = kappa * v_h  # yaw rate about the true vertical

    # Body axes: x along the tangent, then roll about it. Building the frame
    # from the tangent rather than from Euler angles removes any ambiguity
    # about which sign convention "pitch" follows in an ENU frame.
    up = np.zeros((n, 3))
    up[:, 2] = 1.0
    y0 = np.cross(up, tangent)
    y0 /= np.linalg.norm(y0, axis=1, keepdims=True)
    z0 = np.cross(tangent, y0)

    cr, sr = np.cos(roll)[:, None], np.sin(roll)[:, None]
    y_b = cr * y0 - sr * z0
    z_b = sr * y0 + cr * z0
    R_nb = np.stack([tangent, y_b, z_b], axis=2)  # columns are the body axes

    # -- specific force and angular rate ------------------------------------
    gravity = np.zeros((n, 3))
    gravity[:, 2] = G0
    # f = R^T (a - g) with g pointing down, i.e. R^T (a + G0 * up).
    accel_body = np.einsum("nji,nj->ni", R_nb, acc + gravity)

    # Roll rate. The yaw and pitch terms below are closed form, but roll is
    # defined through the *interpolated* curvature table, so its analytic
    # derivative would mean differentiating the interpolant -- and a coarse
    # d(kappa)/ds misses the roll that the interpolated kappa actually produces
    # at a bend entry. Differencing the roll signal itself is simpler and
    # exactly consistent with the attitude sequence, which is what matters:
    # a gyro that disagrees with its own attitude is the one error that would
    # invalidate every heading result downstream.
    rolldot = np.gradient(roll, t) if n > 2 else np.zeros(n)

    # Body rate. The frame above is built as R = R_path @ Rx(-roll) -- the roll
    # block is the transpose of the textbook Rx -- so the roll term subtracts and
    # the pitch/yaw mixing carries Rx(+roll). Getting this backwards flips the
    # sign of the measured roll rate, which a level-road test would never catch
    # because the yaw channel is unaffected when the pitch is zero.
    psidot = omega_z
    croll, sroll = np.cos(roll), np.sin(roll)
    gyro_body = np.stack(
        [
            psidot * sth - rolldot,
            -thdot * croll - psidot * cth * sroll,
            -thdot * sroll + psidot * cth * croll,
        ],
        axis=1,
    )

    return GroundTruth(
        t=t,
        s=s,
        v=v3,
        pos_enu=pos,
        vel_enu=vel,
        R_nb=R_nb,
        psi=psi,
        roll=roll,
        kappa=kappa,
        a_long=a3,
        a_lat=a_lat,
        omega_z=omega_z,
        accel_ideal=accel_body,
        gyro_ideal=gyro_body,
        vehicle=vehicle.name,
        route=route_name,
    )
