"""Command-line entry point.

    python -m setu.cli experiment --route curvy_a_road --open
    python -m setu.cli outage --route straight_motorway --device phone_flagship
    python -m setu.cli routes
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import numpy as np

from .mapping.routes import route_names
from .sensors.types import TIER_DESCRIPTIONS
from .sim.sensors import DEVICES

DEFAULT_OUT = Path("out")


def _cmd_routes(_: argparse.Namespace) -> int:
    print("routes:")
    for name in route_names():
        print(f"  {name}")
    print("\ndevices:")
    for name, dev in DEVICES.items():
        print(f"  {name:18s} {dev.rate_hz:6.0f} Hz")
    print("\ntiers:")
    for tier, desc in TIER_DESCRIPTIONS.items():
        print(f"  {tier}  {desc}")
    return 0


def _cmd_experiment(args: argparse.Namespace) -> int:
    from .eval import run_falsification
    from .report import write_report
    from .sim.sensors import DEVICES

    device = DEVICES[args.device]
    print(f"simulating {args.route} / {device.name} / {args.outage:.0f} s blackout ...")
    result = run_falsification(
        route=args.route,
        route_length_m=args.length,
        device=device,
        outage_start_s=args.start,
        outage_s=args.outage,
        seed=args.seed,
    )

    print(f"\ntier {result.tier} / {args.route}")
    for tr in sorted(result.traces, key=lambda t: -t.metrics.fpe_m):
        m = tr.metrics
        score = result.scores.get(tr.label, float("nan"))
        score_txt = "     -" if not np.isfinite(score) else f"{score:6.2f}"
        print(
            f"  {tr.label:18s} final {m.fpe_m:9.2f} m   drift {m.drift_ratio * 100:7.3f}%"
            f"   anchors {m.n_anchors:3d}   reset {score_txt}"
        )
    print(f"\n  verdict: {result.verdict}\n")

    out = Path(args.out or DEFAULT_OUT / f"setu-{args.route}.html")
    write_report(result, out, title=f"SETU · {args.route}")
    print(f"report: {out.resolve()}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def _cmd_outage(args: argparse.Namespace) -> int:
    from .eval.experiment import BASELINES, run_outage
    from .sim.sensors import DEVICES, simulate_drive

    device = DEVICES[args.device]
    end = args.start + args.outage
    drive = simulate_drive(
        args.route,
        route_length_m=args.length,
        device=device,
        outages=((args.start, end),),
        seed=args.seed,
    )
    if drive.truth.t[-1] < end + 5.0:
        print(
            f"route is only {drive.truth.t[-1]:.0f} s long; use --length to make it longer",
            file=sys.stderr,
        )
        return 2
    the_map = drive.path.perturbed(1.5, np.random.default_rng(0))
    trace = run_outage(
        drive, the_map, BASELINES["SETU"], start_s=args.start, end_s=end, label="SETU"
    )
    m = trace.metrics
    print(f"tier {m.tier} / {args.route} / {device.name}")
    for note in trace.notes:
        print(f"  {note}")
    print(
        f"\n  blackout {m.distance_m:,.0f} m over {m.duration_s:.0f} s\n"
        f"  final error   {m.fpe_m:8.2f} m   ({m.drift_ratio * 100:.3f}% of distance)\n"
        f"  error p90     {m.horizontal.p90:8.2f} m\n"
        f"  along p90     {m.along_track.p90:8.2f} m\n"
        f"  cross p90     {m.cross_track.p90:8.2f} m\n"
        f"  lane-level    {m.lane_keeping_rate * 100:8.0f}%\n"
        f"  3-sigma cov   {m.sigma_coverage_3 * 100:8.0f}%\n"
        f"  anchors       {m.n_anchors:8d}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="setu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--route", default="curvy_a_road", choices=route_names())
        p.add_argument("--device", default="phone_mid", choices=sorted(DEVICES))
        p.add_argument("--length", type=float, default=5000.0, help="route length, m")
        p.add_argument("--start", type=float, default=150.0, help="blackout start, s")
        p.add_argument("--outage", type=float, default=60.0, help="blackout duration, s")
        p.add_argument("--seed", type=int, default=11)

    p_exp = sub.add_parser("experiment", help="run the falsification experiment and report")
    common(p_exp)
    p_exp.add_argument("--out", help="output HTML path")
    p_exp.add_argument("--open", action="store_true", help="open the report in a browser")
    p_exp.set_defaults(func=_cmd_experiment)

    p_out = sub.add_parser("outage", help="score a single blackout")
    common(p_out)
    p_out.set_defaults(func=_cmd_outage)

    p_routes = sub.add_parser("routes", help="list routes, devices and tiers")
    p_routes.set_defaults(func=_cmd_routes)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
