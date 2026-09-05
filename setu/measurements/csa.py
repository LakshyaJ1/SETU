"""CSA -- Curvature-Signature Alignment.

Classical map matching takes noisy *positions* and asks which road produced
them. During a blackout there are no positions -- that is the whole problem. But
there is shape, and shape is accurate: heading comes from a single integration
of a bias-compensated gyro, so after 60 s its error is under a degree while
position error is hundreds of metres.

So the question is inverted (``docs/03-approach.md`` 3.5): *at what arc length
and what speed scale does my measured heading profile best explain the road's
heading profile?*

    J(s0, alpha) = sum_t w(t) [ psi_imu(t) - psi_map(s0 + alpha * s_hat(t)) ]^2

Two unknowns, both nuisance-free: the entry offset ``s0`` is the answer, and
``alpha`` is a residual speed scale solved jointly. Solving for ``alpha`` rather
than assuming it is what separates this from the prior art, which assumes a
known speed source (an odometer or OBD) and matches a metric polyline. A phone
has no speed sensor, so the scale-free version is the one that is usable.

The important honesty: ``dJ/ds0`` carries information only where the map is
curved. **On a straight road CSA is blind, and it must say so** -- which it
does, through a sigma read off the curvature of J at the minimum. That blindness
is exactly why SVO and CTS exist.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..mapping.road import RoadPath, wrap_angle

__all__ = ["CsaConfig", "CsaFix", "align_heading_profile"]


@dataclass(frozen=True)
class CsaConfig:
    """Search extent and acceptance thresholds."""

    s0_window_m: float = 250.0  # +/- search range around the prior
    s0_step_m: float = 1.0
    alpha_min: float = 0.90
    alpha_max: float = 1.10
    alpha_steps: int = 21
    min_window_m: float = 120.0  # too short a window has no shape to match
    max_sigma_m: float = 40.0  # beyond this the fix is not worth applying
    min_turn_rad: float = 0.12  # total |heading change| the window must contain
    # The cost surface is evaluated on a grid, so window length multiplies
    # directly into runtime. Heading is smooth over metres -- a 30 s window at
    # 200 Hz holds 6000 samples but only about 150 samples' worth of shape --
    # so the window is decimated before matching. Without this a single fix
    # costs 60 million interpolations and the sweep does not finish.
    max_window_samples: int = 160

    # The Gauss-Newton sigma read off the cost curvature assumes independent
    # residuals. They are not: map geometry error is smooth over tens of metres
    # and the gyro's heading bias is constant across the window, so the
    # effective sample count is a small fraction of the real one. Measured
    # against the simulator, the raw figure was ~7x optimistic on roundabout and
    # urban routes -- 0.46 m claimed against 3.45 m actual.
    sigma_inflation: float = 2.5
    # CSA cannot locate a vehicle better than the map locates the road. This is
    # the floor, and on well-shaped routes it is the dominant term.
    map_sigma_m: float = 2.5


@dataclass(frozen=True)
class CsaFix:
    """An along-track pseudo-measurement with a calibrated uncertainty."""

    s: float  # arc length of the window's *end*, metres along the edge
    sigma_s: float
    alpha: float  # residual speed scale that best explained the window
    cost: float
    observable: bool
    reason: str = ""
    position_xy: np.ndarray | None = None


def align_heading_profile(
    path: RoadPath,
    psi_imu: np.ndarray,
    s_hat: np.ndarray,
    *,
    s0_prior: float,
    config: CsaConfig | None = None,
) -> CsaFix:
    """Register a measured heading profile against the map.

    ``psi_imu`` is the unwrapped heading history over the window and ``s_hat``
    the nominal distance travelled, both sampled on the same grid. ``s0_prior``
    is where the filter currently believes the window started.

    Only heading *differences* are matched, not absolute heading: the constant
    offset between the gyro's heading and the map's is a nuisance carrying no
    information about position, and removing it makes the result independent of
    the initial heading error, which is the largest error present.
    """
    cfg = config or CsaConfig()
    psi_imu = np.asarray(psi_imu, dtype=float)
    s_hat = np.asarray(s_hat, dtype=float)

    if len(psi_imu) < 8 or len(psi_imu) != len(s_hat):
        return CsaFix(s0_prior, np.inf, 1.0, np.inf, False, "window too short")

    span = float(s_hat[-1] - s_hat[0])
    if span < cfg.min_window_m:
        return CsaFix(s0_prior, np.inf, 1.0, np.inf, False, f"only {span:.0f} m of travel")

    # Shape content. A window with no turning cannot locate anything along a
    # road, and reporting a confident answer from one would be a lie.
    turn = float(np.abs(psi_imu - psi_imu[0]).max())
    if turn < cfg.min_turn_rad:
        return CsaFix(
            s0_prior, np.inf, 1.0, np.inf, False, f"straight ({np.degrees(turn):.1f} deg)"
        )

    # Decimate before matching: the cost grid is evaluated for every offset and
    # scale, so window length multiplies straight into runtime, and a 200 Hz
    # heading trace holds no more shape than a metre-spaced one.
    if len(psi_imu) > cfg.max_window_samples:
        take = np.linspace(0, len(psi_imu) - 1, cfg.max_window_samples).astype(int)
        psi_imu, s_hat = psi_imu[take], s_hat[take]

    psi_rel = psi_imu - psi_imu[0]
    s_rel = s_hat - s_hat[0]

    offsets = np.arange(
        s0_prior - cfg.s0_window_m, s0_prior + cfg.s0_window_m + cfg.s0_step_m, cfg.s0_step_m
    )
    offsets = offsets[(offsets >= 0.0) & (offsets + span * cfg.alpha_min <= path.length)]
    if len(offsets) < 5:
        return CsaFix(s0_prior, np.inf, 1.0, np.inf, False, "search window off the edge")
    alphas = np.linspace(cfg.alpha_min, cfg.alpha_max, cfg.alpha_steps)

    # Evaluate J on the grid. Vectorised over offsets for each alpha; the map
    # heading is unwrapped, so relative headings subtract cleanly.
    cost = np.empty((len(offsets), len(alphas)))
    for j, alpha in enumerate(alphas):
        query = offsets[:, None] + alpha * s_rel[None, :]
        psi_map = np.interp(query, path.s, path.psi)
        psi_map_rel = psi_map - psi_map[:, :1]
        cost[:, j] = np.mean(wrap_angle(psi_rel[None, :] - psi_map_rel) ** 2, axis=1)

    flat = int(np.argmin(cost))
    i0, j0 = np.unravel_index(flat, cost.shape)
    best_cost = float(cost[i0, j0])

    # Sigma from the curvature of J along s0 at the minimum. A sharp trough is a
    # confident fix; a flat one -- a gently curving or straight road -- yields a
    # large sigma, which is how CSA reports its own blindness rather than
    # asserting a position it cannot support.
    if 0 < i0 < len(offsets) - 1:
        c_lo, c_mid, c_hi = cost[i0 - 1, j0], cost[i0, j0], cost[i0 + 1, j0]
        curvature = (c_lo - 2.0 * c_mid + c_hi) / (cfg.s0_step_m**2)
        delta = 0.0
        denom = c_lo - 2.0 * c_mid + c_hi
        if abs(denom) > 1e-30:
            delta = float(np.clip(0.5 * (c_lo - c_hi) / denom, -1.0, 1.0))
        s0_hat = float(offsets[i0] + delta * cfg.s0_step_m)
        # J is a mean squared residual, so 2 * J_min / curvature is the variance
        # of the offset in the Gauss-Newton sense.
        if curvature > 0:
            raw = float(np.sqrt(max(2.0 * best_cost / curvature, 1e-9)))
            sigma = float(np.hypot(cfg.sigma_inflation * raw, cfg.map_sigma_m))
        else:
            sigma = np.inf
    else:
        s0_hat, sigma = float(offsets[i0]), np.inf

    alpha_hat = float(alphas[j0])
    observable = np.isfinite(sigma) and sigma <= cfg.max_sigma_m
    s_end = s0_hat + alpha_hat * span
    s_end = float(np.clip(s_end, 0.0, path.length))

    return CsaFix(
        s=s_end,
        sigma_s=float(sigma),
        alpha=alpha_hat,
        cost=best_cost,
        observable=bool(observable),
        reason="" if observable else f"sigma {sigma:.0f} m exceeds gate",
        position_xy=path.position_at(s_end) if observable else None,
    )
