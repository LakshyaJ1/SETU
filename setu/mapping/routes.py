"""Canonical test routes, one per row of the observability matrix.

``docs/03-approach.md`` 3.11 argues that no two SETU channels share a blind spot.
That claim is only testable if the scenarios that isolate each blind spot exist
as concrete geometry, so each builder here corresponds to a row of that table.
The straight motorway is the important one: it is the single case where every
geometric channel fails and only SVO survives.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .road import RoadPath

__all__ = ["ROUTES", "build_route", "route_names"]


def _straight_motorway(length_m: float = 3000.0) -> RoadPath:
    """Dead straight. CSA is blind here by construction -- the SVO test case."""
    return RoadPath.from_curvature_profile([(length_m, 0.0)], edge_id="straight_motorway")


def _gentle_motorway(length_m: float = 3000.0) -> RoadPath:
    """Motorway-grade curves: radii of 800-2000 m, the weakest useful signal."""
    rng = np.random.default_rng(11)
    segments: list[tuple[float, float]] = []
    remaining = length_m
    while remaining > 0:
        seg = min(float(rng.uniform(250.0, 500.0)), remaining)
        radius = float(rng.uniform(800.0, 2000.0)) * rng.choice([-1.0, 1.0])
        segments.append((seg, 1.0 / radius if rng.random() < 0.6 else 0.0))
        remaining -= seg
    return RoadPath.from_curvature_profile(segments, edge_id="gentle_motorway")


def _curvy_a_road(length_m: float = 3000.0) -> RoadPath:
    """Rural A-road: radii of 90-300 m, a curvature landmark every ~200 m."""
    rng = np.random.default_rng(7)
    segments: list[tuple[float, float]] = []
    remaining = length_m
    sign = 1.0
    while remaining > 0:
        straight = min(float(rng.uniform(40.0, 120.0)), remaining)
        segments.append((straight, 0.0))
        remaining -= straight
        if remaining <= 0:
            break
        bend = min(float(rng.uniform(60.0, 160.0)), remaining)
        radius = float(rng.uniform(90.0, 300.0))
        segments.append((bend, sign / radius))
        remaining -= bend
        sign *= -1.0
    return RoadPath.from_curvature_profile(segments, edge_id="curvy_a_road")


def _urban_canyon(length_m: float = 2000.0) -> RoadPath:
    """City blocks: straights of 80-200 m joined by 90 deg corners of radius 12 m."""
    rng = np.random.default_rng(3)
    corner_len = 0.5 * np.pi * 12.0  # quarter circle, radius 12 m
    segments: list[tuple[float, float]] = []
    remaining = length_m
    sign = 1.0
    while remaining > corner_len:
        block = min(float(rng.uniform(80.0, 200.0)), remaining - corner_len)
        segments.append((block, 0.0))
        remaining -= block
        segments.append((corner_len, sign / 12.0))
        remaining -= corner_len
        sign = float(rng.choice([-1.0, 1.0]))
    if remaining > 1.0:
        segments.append((remaining, 0.0))
    return RoadPath.from_curvature_profile(segments, edge_id="urban_canyon")


def _roundabout_route(length_m: float = 2000.0, radius_m: float = 20.0) -> RoadPath:
    """Approach roads punctuated by roundabouts.

    ``docs/03-approach.md`` 3.5 calls a roundabout the single most informative
    landmark type: a 360 deg signature with a known radius. IO-VNBD's ``V-M``
    subset alone contains 30 of them.
    """
    rng = np.random.default_rng(5)
    segments: list[tuple[float, float]] = []
    remaining = length_m
    while remaining > 0:
        approach = min(float(rng.uniform(150.0, 350.0)), remaining)
        segments.append((approach, 0.0))
        remaining -= approach
        if remaining <= 0:
            break
        # Three-quarters of a circle: enter, pass two exits, leave.
        arc = min(0.75 * 2.0 * np.pi * radius_m, remaining)
        segments.append((arc, -1.0 / radius_m))  # UK/India convention: clockwise
        remaining -= arc
    return RoadPath.from_curvature_profile(segments, edge_id="roundabout_route")


def _parking_helix(levels: int = 4, radius_m: float = 11.0, deck_m: float = 45.0) -> RoadPath:
    """Multi-level car park: straight decks joined by helical ramps.

    Planar geometry only -- the vertical component is supplied by the simulator's
    grade profile, and it is the barometer that resolves the level
    (``docs/03-approach.md`` 3.8).
    """
    turn = 2.0 * np.pi * radius_m  # one full turn of the helix per level
    segments: list[tuple[float, float]] = []
    for _ in range(levels):
        segments.append((deck_m, 0.0))
        segments.append((turn, 1.0 / radius_m))
    segments.append((deck_m, 0.0))
    return RoadPath.from_curvature_profile(segments, edge_id="parking_helix")


ROUTES: dict[str, Callable[..., RoadPath]] = {
    "straight_motorway": _straight_motorway,
    "gentle_motorway": _gentle_motorway,
    "curvy_a_road": _curvy_a_road,
    "urban_canyon": _urban_canyon,
    "roundabout_route": _roundabout_route,
    "parking_helix": _parking_helix,
}


def route_names() -> list[str]:
    """Names accepted by :func:`build_route`."""
    return sorted(ROUTES)


def build_route(name: str, **kwargs) -> RoadPath:
    """Build one of the canonical routes by name."""
    try:
        builder = ROUTES[name]
    except KeyError:
        raise KeyError(f"unknown route {name!r}; available: {route_names()}") from None
    return builder(**kwargs)
