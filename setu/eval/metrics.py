"""Error metrics for a GNSS-outage window.

``docs/08-evaluation.md`` 8.2 sets the reporting rule this module enforces:
**every metric is reported as p50/p90/p95/max, never as a bare mean**, because
the tail is what a driver experiences. A system that is excellent on median and
occasionally 300 m wrong is worse, in use, than one that is uniformly mediocre.

Position error is also decomposed into along-track and cross-track in the road
frame. That split is diagnostic rather than decorative: along-track error is a
*speed* problem and cross-track error is a *heading* problem, and they are fixed
by different modules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

__all__ = ["ErrorStats", "OutageMetrics", "summarise", "evaluate_outage"]


@dataclass(frozen=True)
class ErrorStats:
    """Percentile summary of one error series."""

    p50: float
    p90: float
    p95: float
    max: float
    mean: float
    n: int

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def summarise(values: np.ndarray) -> ErrorStats:
    """Percentile summary, robust to an empty input."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        nan = float("nan")
        return ErrorStats(nan, nan, nan, nan, nan, 0)
    return ErrorStats(
        p50=float(np.percentile(v, 50)),
        p90=float(np.percentile(v, 90)),
        p95=float(np.percentile(v, 95)),
        max=float(v.max()),
        mean=float(v.mean()),
        n=int(v.size),
    )


@dataclass
class OutageMetrics:
    """Everything worth knowing about one simulated blackout."""

    start_s: float
    end_s: float
    duration_s: float
    distance_m: float

    fpe_m: float  # final position error -- what a missed exit depends on
    drift_ratio: float  # FPE / distance: the SIH gate
    ate_m: float  # RMS error across the window
    horizontal: ErrorStats = field(default_factory=lambda: summarise(np.array([])))
    along_track: ErrorStats = field(default_factory=lambda: summarise(np.array([])))
    cross_track: ErrorStats = field(default_factory=lambda: summarise(np.array([])))
    heading_err_deg: float = float("nan")
    speed_err_mps: ErrorStats = field(default_factory=lambda: summarise(np.array([])))
    sigma_coverage_3: float = float("nan")  # fraction of errors inside 3 sigma
    lane_keeping_rate: float = float("nan")  # fraction with |cross-track| < 1.8 m
    n_anchors: int = 0
    tier: str = "?"

    def as_row(self) -> dict[str, object]:
        """Flat record in the shape of the reporting template in 8.8."""
        return {
            "tier": self.tier,
            "outage_s": round(self.duration_s, 1),
            "distance_m": round(self.distance_m, 1),
            "drift_p50": round(self.horizontal.p50 / max(self.distance_m, 1e-9), 5),
            "drift_ratio": round(self.drift_ratio, 5),
            "fpe_m": round(self.fpe_m, 2),
            "along_p90": round(self.along_track.p90, 2),
            "cross_p90": round(self.cross_track.p90, 2),
            "sigma3_cov": round(self.sigma_coverage_3, 3),
            "lane_rate": round(self.lane_keeping_rate, 3),
            "anchors": self.n_anchors,
        }


def evaluate_outage(
    t: np.ndarray,
    est_xy: np.ndarray,
    true_xy: np.ndarray,
    *,
    true_heading: np.ndarray,
    est_heading: np.ndarray | None = None,
    true_speed: np.ndarray | None = None,
    est_speed: np.ndarray | None = None,
    sigma_pos: np.ndarray | None = None,
    distance_m: float | None = None,
    n_anchors: int = 0,
    tier: str = "?",
) -> OutageMetrics:
    """Score one outage window. All arrays are already restricted to it.

    Along- and cross-track are taken in the frame of the vehicle's *true*
    heading, so the decomposition describes the error rather than the
    estimator's opinion of its own orientation.
    """
    t = np.asarray(t, dtype=float)
    est_xy = np.asarray(est_xy, dtype=float)[:, :2]
    true_xy = np.asarray(true_xy, dtype=float)[:, :2]
    if len(t) < 2:
        raise ValueError("outage window needs at least two epochs")

    delta = est_xy - true_xy
    horiz = np.linalg.norm(delta, axis=1)

    fwd = np.stack([np.cos(true_heading), np.sin(true_heading)], axis=1)
    left = np.stack([-np.sin(true_heading), np.cos(true_heading)], axis=1)
    along = np.einsum("ij,ij->i", delta, fwd)
    cross = np.einsum("ij,ij->i", delta, left)

    if distance_m is None:
        distance_m = float(np.sum(np.linalg.norm(np.diff(true_xy, axis=0), axis=1)))
    distance_m = max(float(distance_m), 1e-9)

    heading_err = float("nan")
    if est_heading is not None:
        d = np.asarray(est_heading) - np.asarray(true_heading)
        heading_err = float(np.degrees(abs(np.arctan2(np.sin(d[-1]), np.cos(d[-1])))))

    speed_stats = summarise(np.array([]))
    if est_speed is not None and true_speed is not None:
        speed_stats = summarise(np.abs(np.asarray(est_speed) - np.asarray(true_speed)))

    coverage = float("nan")
    if sigma_pos is not None:
        s = np.asarray(sigma_pos, dtype=float)
        good = s > 0
        if good.any():
            coverage = float(np.mean(horiz[good] < 3.0 * s[good]))

    return OutageMetrics(
        start_s=float(t[0]),
        end_s=float(t[-1]),
        duration_s=float(t[-1] - t[0]),
        distance_m=distance_m,
        fpe_m=float(horiz[-1]),
        drift_ratio=float(horiz[-1] / distance_m),
        ate_m=float(np.sqrt(np.mean(horiz**2))),
        horizontal=summarise(horiz),
        along_track=summarise(np.abs(along)),
        cross_track=summarise(np.abs(cross)),
        heading_err_deg=heading_err,
        speed_err_mps=speed_stats,
        sigma_coverage_3=coverage,
        # "Lane-level" made operational: 1.8 m is half a 3.6 m lane.
        lane_keeping_rate=float(np.mean(np.abs(cross) < 1.8)),
        n_anchors=n_anchors,
        tier=tier,
    )
