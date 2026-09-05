"""The falsification experiment of ``docs/08-evaluation.md`` 8.6.

The central claim of SETU is not "our error is small". It is a claim about the
*shape* of the error curve:

    error should be bounded by anchor spacing, not by elapsed time.

That is falsifiable, and this module is what falsifies it. Plot horizontal
error against distance travelled during a blackout, mark every curvature
landmark, and look:

* **SETU predicts a sawtooth** -- error accumulates between landmarks and
  *drops* at each one, with no long-run growth.
* **A classical stack predicts monotone growth**, linear in distance if it is
  velocity-scale limited and super-linear if it is integration limited.

If the SETU curve does not visibly reset at landmarks, the thesis of 3.1 is
falsified and the honest response is to fall back to the classical stack plus
the speed heads. The doc is explicit that this should be run *before* building
the app, because it is cheap and it is the single highest-information
experiment available.

:func:`sawtooth_score` is the quantitative version of "visibly resets": it
measures how much of the error accumulated between anchors is given back at
them. A classical baseline scores near zero by construction, because nothing in
it can reduce position error without GNSS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..mapping.road import RoadPath
from ..pipeline import PipelineConfig, run_pipeline
from ..sim.sensors import DriveResult, simulate_drive
from .metrics import OutageMetrics, evaluate_outage

__all__ = [
    "OutageTrace",
    "ExperimentResult",
    "BASELINES",
    "run_outage",
    "sawtooth_score",
    "run_falsification",
]


# The ablation flags double as the baseline definitions of 8.4, so a baseline is
# a config rather than a separate implementation that could drift out of date.
BASELINES: dict[str, PipelineConfig] = {
    # B1: pure strapdown on the phone IMU. Shows the t^2/t^3 divergence.
    "B1_ins": PipelineConfig(
        use_svo=False, use_cts=False, use_csa=False, use_nhc=False, use_zupt=False
    ),
    # B2: INS + NHC + ZUPT, well tuned. THE baseline -- published equivalent is
    # about 3.1 %/km in a tunnel with a phone. Beating only B1 proves nothing.
    "B2_ins_nhc_zupt": PipelineConfig(use_svo=False, use_cts=False, use_csa=False),
    # Speed aiding but no map: isolates what registration contributes.
    "B4_speed_only": PipelineConfig(use_csa=False),
    # The full system.
    "SETU": PipelineConfig(),
}


@dataclass
class OutageTrace:
    """Error against distance through one blackout, plus where the anchors were."""

    label: str
    t: np.ndarray
    distance_m: np.ndarray  # distance travelled since the outage began
    error_m: np.ndarray  # horizontal position error
    sigma_m: np.ndarray
    anchor_distance_m: np.ndarray  # where registration fixes landed
    metrics: OutageMetrics
    est_xy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    true_xy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    anchor_xy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    channels: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ExperimentResult:
    """Everything the write-up and the UI need from one falsification run."""

    route: str
    tier: str
    outage_s: float
    traces: list[OutageTrace]
    scores: dict[str, float]
    verdict: str


def run_outage(
    drive: DriveResult,
    the_map: RoadPath | None,
    config: PipelineConfig,
    *,
    start_s: float,
    end_s: float,
    label: str,
) -> OutageTrace:
    """Run one configuration through one blackout and score the window."""
    sol = run_pipeline(drive.log, path=the_map, config=config)
    gt = drive.truth

    window = (sol.t >= start_s) & (sol.t <= end_s)
    if window.sum() < 3:
        raise ValueError("outage window does not overlap the solution")

    def interp(col: np.ndarray) -> np.ndarray:
        return np.interp(sol.t[window], gt.t, col)

    true_xy = np.stack([interp(gt.pos_enu[:, 0]), interp(gt.pos_enu[:, 1])], axis=1)
    true_psi = interp(np.unwrap(gt.psi))
    true_s = interp(gt.s)
    est_xy = sol.pos_enu[window][:, :2]

    distance = true_s - true_s[0]
    error = np.linalg.norm(est_xy - true_xy, axis=1)

    metrics = evaluate_outage(
        sol.t[window],
        est_xy,
        true_xy,
        true_heading=true_psi,
        est_heading=sol.heading[window],
        true_speed=interp(gt.v),
        est_speed=sol.speed[window],
        sigma_pos=sol.sigma_pos[window],
        distance_m=float(distance[-1]),
        n_anchors=sum(1 for a in sol.anchors if start_s <= a[0] <= end_s),
        tier=sol.tier,
    )

    anchor_d = np.array(
        [
            float(np.interp(a[0], gt.t, gt.s) - true_s[0])
            for a in sol.anchors
            if start_s <= a[0] <= end_s
        ]
    )
    anchor_xy = (
        np.array([the_map.position_at(true_s[0] + float(d)) for d in anchor_d])
        if the_map is not None and len(anchor_d)
        else np.zeros((0, 2))
    )
    # Channel availability restricted to the blackout window.
    channels = {}
    for name, (ct, cv) in sol.channels.items():
        m = (ct >= start_s) & (ct <= end_s)
        if m.sum() > 2:
            channels[name] = (ct[m], cv[m])

    return OutageTrace(
        label=label,
        t=sol.t[window],
        distance_m=distance,
        error_m=error,
        sigma_m=sol.sigma_pos[window],
        anchor_distance_m=anchor_d,
        metrics=metrics,
        est_xy=est_xy,
        true_xy=true_xy,
        anchor_xy=anchor_xy,
        channels=channels,
        notes=sol.notes,
    )


def sawtooth_score(trace: OutageTrace, *, window_m: float = 40.0) -> float:
    """How much of the accumulated error is given back at anchors, in [0, 1].

    For each anchor, compare the error just before it with the error just after.
    The score is total reduction divided by total accumulation, so:

    * ~0 means error only ever grows -- the classical picture, and the outcome
      that would falsify the thesis;
    * a clearly positive value means error is being *reset* at landmarks rather
      than merely growing more slowly, which is the structural claim.

    Returns NaN when there are no anchors, which is itself the answer on a
    straight road.
    """
    if len(trace.anchor_distance_m) == 0:
        return float("nan")

    reductions = 0.0
    for d in trace.anchor_distance_m:
        before = (trace.distance_m >= d - window_m) & (trace.distance_m < d)
        after = (trace.distance_m > d) & (trace.distance_m <= d + window_m)
        if before.sum() < 2 or after.sum() < 2:
            continue
        drop = float(trace.error_m[before].max() - trace.error_m[after].min())
        reductions += max(drop, 0.0)

    growth = float(np.sum(np.clip(np.diff(trace.error_m), 0.0, None)))
    if growth <= 1e-9:
        return float("nan")
    return float(np.clip(reductions / growth, 0.0, 1.0))


def run_falsification(
    *,
    route: str = "curvy_a_road",
    route_length_m: float = 5000.0,
    device=None,
    outage_start_s: float = 150.0,
    outage_s: float = 60.0,
    seed: int = 11,
    map_error_m: float = 1.5,
    labels: tuple[str, ...] = ("B1_ins", "B2_ins_nhc_zupt", "SETU"),
) -> ExperimentResult:
    """Run the experiment and return a verdict.

    The same drive is replayed through every configuration, so the comparison
    isolates the estimator: identical sensor data, identical noise, identical
    road, only the enabled channels differ.
    """
    from ..sim.sensors import PHONE_MID

    device = device or PHONE_MID
    end_s = outage_start_s + outage_s
    drive = simulate_drive(
        route,
        route_length_m=route_length_m,
        device=device,
        outages=((outage_start_s, end_s),),
        seed=seed,
    )
    if drive.truth.t[-1] < end_s + 5.0:
        raise ValueError(
            f"route is only {drive.truth.t[-1]:.0f} s long; "
            f"an outage ending at {end_s:.0f} s does not fit"
        )

    the_map = drive.path.perturbed(map_error_m, np.random.default_rng(0))

    traces: list[OutageTrace] = []
    for label in labels:
        traces.append(
            run_outage(
                drive,
                the_map,
                BASELINES[label],
                start_s=outage_start_s,
                end_s=end_s,
                label=label,
            )
        )

    scores = {tr.label: sawtooth_score(tr) for tr in traces}
    setu = next((tr for tr in traces if tr.label == "SETU"), None)
    classical = next((tr for tr in traces if tr.label == "B2_ins_nhc_zupt"), None)

    if setu is None:
        verdict = "inconclusive: SETU was not run"
    elif len(setu.anchor_distance_m) == 0:
        verdict = (
            "no anchors: registration was never observable on this route, so the "
            "sawtooth cannot be tested here. Expected on a straight road."
        )
    elif not np.isfinite(scores.get("SETU", float("nan"))) or scores["SETU"] < 0.05:
        verdict = (
            "FALSIFIED on this run: error did not reset at landmarks. "
            "See docs/08-evaluation.md 8.6 -- fall back to the classical stack."
        )
    elif classical is not None and setu.metrics.fpe_m < 0.5 * classical.metrics.fpe_m:
        verdict = (
            f"supported: error resets at {len(setu.anchor_distance_m)} anchors "
            f"(reset ratio {scores['SETU']:.2f}), and final error is "
            f"{classical.metrics.fpe_m / max(setu.metrics.fpe_m, 1e-9):.1f}x better than B2."
        )
    else:
        verdict = (
            f"partial: error resets at anchors (ratio {scores['SETU']:.2f}) but the "
            "final-error advantage over B2 is under 2x on this run."
        )

    return ExperimentResult(
        route=route,
        tier=traces[0].metrics.tier if traces else "?",
        outage_s=outage_s,
        traces=traces,
        scores=scores,
        verdict=verdict,
    )
