"""Inline SVG charts. No plotting library, no CDN, no runtime dependency.

Drawn by hand because the page must open from a file with no network -- which is
the same constraint the product itself is built around -- and because the hero
chart needs marks a general-purpose library does not have: anchor rules that
show *where* error was given back, annotated with how much.

Chart discipline follows the dataviz procedure: form chosen from the data's job,
categorical hues assigned in fixed order and validator-checked (see theme.py),
2px marks, recessive grid, a legend for every multi-series plot plus selective
direct labels so identity is never carried by colour alone.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass

import numpy as np

from .theme import SERIES, TOKENS

__all__ = ["error_vs_distance", "trajectory", "coverage_strip", "Frame"]


@dataclass(frozen=True)
class Frame:
    """Plot box in user units."""

    width: float = 1000.0
    height: float = 460.0
    left: float = 68.0
    right: float = 132.0  # room for direct labels at the line ends
    top: float = 34.0
    bottom: float = 56.0

    @property
    def x0(self) -> float:
        return self.left

    @property
    def x1(self) -> float:
        return self.width - self.right

    @property
    def y0(self) -> float:
        return self.height - self.bottom

    @property
    def y1(self) -> float:
        return self.top


def _esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _fmt(v: float, unit: str = "") -> str:
    if not math.isfinite(v):
        return "—"
    if abs(v) >= 100:
        out = f"{v:,.0f}"
    elif abs(v) >= 10:
        out = f"{v:.1f}"
    else:
        out = f"{v:.2f}"
    return f"{out}{unit}"


def _tick_label(v: float) -> str:
    """Axis ticks print at the precision the value needs, and no more.

    Routing decade ticks through the general formatter produced a column
    reading 30.0 / 10.0 / 3.00 / 1.00 -- three precisions stacked in one
    tabular column, on a page whose whole type commitment is aligned figures.
    """
    if v >= 1.0:
        return f"{v:,.0f}"
    return f"{v:g}"


def _log_ticks(lo: float, hi: float) -> list[float]:
    """Decade and half-decade ticks spanning the range."""
    candidates = []
    e = math.floor(math.log10(max(lo, 1e-6)))
    while 10.0**e <= hi * 1.5:
        for m in (1.0, 3.0):
            v = m * 10.0**e
            if lo * 0.85 <= v <= hi * 1.15:
                candidates.append(v)
        e += 1
    return candidates or [lo, hi]


def error_vs_distance(
    traces: list,
    *,
    frame: Frame | None = None,
    gate_ratio: float = 0.10,
) -> str:
    """The falsification chart: horizontal error against distance travelled.

    Log-scaled in error, because the series legitimately span three decades --
    sub-metre to hundreds of metres -- and a linear axis would render every
    difference that matters as a flat line on the floor.

    The anchor rules are the point of the whole figure. Each marks a curvature
    registration, and the drop across it is the claim of docs/03-approach.md 3.1
    made visible: error bounded by anchor spacing rather than by elapsed time.
    """
    f = frame or Frame()
    if not traces:
        return ""

    all_err = np.concatenate([np.asarray(t.error_m) for t in traces])
    all_err = all_err[np.isfinite(all_err) & (all_err > 0)]
    lo = max(float(np.percentile(all_err, 0.5)), 0.05)
    hi = float(all_err.max()) * 1.25
    lo = min(lo, 0.5)
    d_max = max(float(np.asarray(t.distance_m).max()) for t in traces)

    def sx(d: float) -> float:
        return f.x0 + (d / max(d_max, 1e-9)) * (f.x1 - f.x0)

    def sy(e: float) -> float:
        e = max(float(e), lo * 0.6)
        frac = (math.log10(e) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        return f.y0 - frac * (f.y0 - f.y1)

    out: list[str] = [
        f'<svg class="chart" viewBox="0 0 {f.width:.0f} {f.height:.0f}" '
        f'role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="Horizontal position error against distance travelled during the '
        f'GNSS blackout, for each configuration.">'
    ]

    # -- grid: recessive, behind everything -------------------------------
    for v in _log_ticks(lo, hi):
        y = sy(v)
        out.append(
            f'<line x1="{f.x0:.1f}" y1="{y:.1f}" x2="{f.x1:.1f}" y2="{y:.1f}" '
            f'stroke="{TOKENS["rule"]}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{f.x0 - 12:.1f}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="tick">{_tick_label(v)}</text>'
        )
    # Round tick values, not fractions of the maximum: "222 m" is an artefact of
    # the axis, "200 m" is a distance a reader can hold on to.
    base = 10 ** math.floor(math.log10(max(d_max / 5.0, 1.0)))
    tick_step = base * 10  # fallback if nothing smaller fits
    for mult in (1, 2, 5, 10):
        if d_max / (base * mult) <= 6:
            tick_step = base * mult
            break
    for d in np.arange(0.0, d_max + tick_step * 0.5, tick_step):
        if d > d_max * 1.001:
            break
        x = sx(float(d))
        out.append(
            f'<line x1="{x:.1f}" y1="{f.y1:.1f}" x2="{x:.1f}" y2="{f.y0:.1f}" '
            f'stroke="{TOKENS["rule"]}" stroke-width="1" opacity="0.55"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{f.y0 + 22:.1f}" text-anchor="middle" '
            f'class="tick">{d:,.0f}</text>'
        )

    # -- the SIH ceiling: 10 % of distance --------------------------------
    # The gate is 10 % of distance, which at 887 m is 89 m -- well above an axis
    # whose top is set by the worst trace. Drawn unclipped it left the frame and
    # took its label to y = -3.9, off-canvas: a fourth, most-prominent curve with
    # no identity at all, on a page whose rule is that identity never rests on
    # colour alone. Clip it, and label the last point that is actually visible.
    ceiling = [
        (sx(d), sy(max(gate_ratio * d, lo)))
        for d in np.linspace(1.0, d_max, 160)
        if sy(max(gate_ratio * d, lo)) >= f.y1
    ]
    if ceiling:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in ceiling)
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{TOKENS["ink_faint"]}" '
            f'stroke-width="1.5" stroke-dasharray="3 5"/>'
        )
        cx, cy = ceiling[-1]
        # If the line exits through the top, label it below and to the left of
        # its exit; if it stays inside, label it at the right-hand end.
        exits_top = cy <= f.y1 + 1.0
        out.append(
            f'<text x="{cx - 8:.1f}" y="{cy + (16 if exits_top else -10):.1f}" '
            f'text-anchor="end" class="annot-muted">'
            f'SIH ceiling · 10% of distance</text>'
        )

    # -- anchors, drawn under the traces ----------------------------------
    setu = next((t for t in traces if t.label == "SETU"), None)
    if setu is not None and len(setu.anchor_distance_m):
        sd = np.asarray(setu.distance_m)
        se = np.asarray(setu.error_m)
        for d in setu.anchor_distance_m:
            x = sx(float(d))
            # The rule runs from the axis up to the trace, and the marker sits ON
            # the trace. Floating the marker at the top of the frame left the
            # reader to infer which drop belonged to which registration, which is
            # the single relationship this whole figure exists to show.
            y_at = sy(float(np.interp(float(d), sd, se)))
            out.append(
                f'<line x1="{x:.1f}" y1="{y_at:.1f}" x2="{x:.1f}" y2="{f.y0:.1f}" '
                f'stroke="{TOKENS["accent"]}" stroke-width="1" stroke-dasharray="2 4" '
                f'opacity="0.45"/>'
            )
            out.append(
                f'<path d="M {x:.1f} {y_at - 5.5:.1f} l 4.4 5.5 l -4.4 5.5 l -4.4 -5.5 z" '
                f'fill="{TOKENS["ground"]}" stroke="{TOKENS["accent_bright"]}" '
                f'stroke-width="1.5"/>'
            )
        out.append(
            f'<text x="{f.x0 + 8:.1f}" y="{f.y0 - 10:.1f}" class="annot-accent">'
            f'{len(setu.anchor_distance_m)} curvature registrations, each one a reset'
            f'</text>'
        )

    # -- traces, SETU drawn last so it sits on top ------------------------
    # Wrapped in the sweep clip. The CSS for this lived in the stylesheet from
    # the start but nothing ever emitted the element, so the page shipped with
    # dead keyframes and no motion at all.
    out.append(
        f'<clipPath id="hero-sweep"><rect class="reveal-rect" x="{f.x0 - 4:.1f}" '
        f'y="{f.y1 - 24:.1f}" width="{f.width - f.x0 + 4:.1f}" '
        f'height="{f.y0 - f.y1 + 48:.1f}"/></clipPath>'
    )
    out.append('<g clip-path="url(#hero-sweep)">')
    ordered = sorted(traces, key=lambda t: t.label == "SETU")
    for tr in ordered:
        spec = SERIES.get(tr.label, SERIES["SETU"])
        d = np.asarray(tr.distance_m)
        e = np.asarray(tr.error_m)
        step = max(len(d) // 900, 1)  # keep the path node count sane
        pts = " ".join(
            f"{sx(float(dd)):.1f},{sy(float(ee)):.1f}"
            for dd, ee in zip(d[::step], e[::step], strict=False)
        )
        dash = f' stroke-dasharray="{spec["dash"]}"' if spec["dash"] else ""
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{spec["color"]}" '
            f'stroke-width="{spec["width"]}" stroke-linejoin="round" '
            f'stroke-linecap="round"{dash}/>'
        )
        # Direct label at the line end -- identity never rests on colour alone.
        yend = sy(float(e[-1]))
        out.append(
            f'<text x="{f.x1 + 10:.1f}" y="{yend + 4:.1f}" class="series-label" '
            f'fill="{spec["color"]}">{_esc(spec["label"].split(" · ")[0])} '
            f'<tspan class="series-value">{_fmt(float(e[-1]))} m</tspan></text>'
        )

    out.append("</g>")  # close the sweep clip

    # -- axis titles ------------------------------------------------------
    out.append(
        f'<text x="{f.x0:.1f}" y="{f.height - 12:.1f}" class="axis-title">'
        f'distance travelled since GNSS was withheld (m)</text>'
    )
    out.append(
        f'<text transform="translate(16 {f.y1 + (f.y0 - f.y1) / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle" class="axis-title">horizontal error (m, log)</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def trajectory(
    true_xy: np.ndarray,
    est_xy: np.ndarray,
    *,
    anchors_xy: np.ndarray | None = None,
    width: float = 1000.0,
    height: float = 420.0,
) -> str:
    """Plan view of the blackout: where the vehicle went, where we thought it was.

    Equal aspect, because this is a map -- stretching one axis to fill a box
    would misrepresent the geometry the whole method is registering against.
    """
    true_xy = np.asarray(true_xy, dtype=float)
    est_xy = np.asarray(est_xy, dtype=float)
    pad = 34.0

    both = np.vstack([true_xy, est_xy])
    lo = both.min(axis=0)
    hi = both.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    scale = min((width - 2 * pad) / span[0], (height - 2 * pad) / span[1])
    cx, cy = (lo + hi) / 2.0

    def proj(p: np.ndarray) -> tuple[float, float]:
        return (
            width / 2.0 + (p[0] - cx) * scale,
            height / 2.0 - (p[1] - cy) * scale,  # north up
        )

    def path(points: np.ndarray, step: int = 1) -> str:
        return " ".join("{:.1f},{:.1f}".format(*proj(p)) for p in points[::step])

    step = max(len(true_xy) // 700, 1)
    out = [
        f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'aria-label="Plan view of the true and estimated paths through the blackout.">'
    ]
    # The truth is drawn as a wide corridor beneath the estimate. It has to be
    # light enough to actually read as "the road" -- at ink_faint it vanished
    # under the estimate entirely, which made the legend's claim untrue.
    out.append(
        f'<polyline points="{path(true_xy, step)}" fill="none" '
        f'stroke="{TOKENS["ink_muted"]}" stroke-width="9" stroke-linejoin="round" '
        f'stroke-linecap="round" opacity="0.5"/>'
    )
    out.append(
        f'<polyline points="{path(est_xy, step)}" fill="none" '
        f'stroke="{TOKENS["accent"]}" stroke-width="2.2" stroke-linejoin="round" '
        f'stroke-linecap="round"/>'
    )

    if anchors_xy is not None and len(anchors_xy):
        for p in np.asarray(anchors_xy, dtype=float):
            x, y = proj(p)
            out.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="none" '
                f'stroke="{TOKENS["accent_bright"]}" stroke-width="1.6"/>'
            )

    sx, sy = proj(true_xy[0])
    ex, ey = proj(true_xy[-1])
    out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="{TOKENS["ink_secondary"]}"/>')
    # Anchor the end labels away from the frame edge; centring them on the marks
    # clipped both of them once the path reached the corners.
    out.append(
        f'<text x="{min(max(sx, pad + 4), width - pad - 4):.1f}" y="{sy - 15:.1f}" '
        f'text-anchor="{"start" if sx < width / 2 else "end"}" class="annot-muted">'
        f'blackout begins</text>'
    )
    out.append(
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="5" fill="none" '
        f'stroke="{TOKENS["ink_secondary"]}" stroke-width="2"/>'
    )
    out.append(
        f'<text x="{min(max(ex, pad + 4), width - pad - 4):.1f}" y="{ey - 15:.1f}" '
        f'text-anchor="{"start" if ex < width / 2 else "end"}" class="annot-muted">'
        f'GNSS returns</text>'
    )

    # Scale bar: a map without one is a picture.
    bar_m = 10 ** math.floor(math.log10(span[0] / 3))
    for mult in (5, 2, 1):
        if bar_m * mult * scale < (width - 2 * pad) * 0.34:
            bar_m *= mult
            break
    bar_px = bar_m * scale
    by = height - 18
    out.append(
        f'<line x1="{pad:.1f}" y1="{by:.1f}" x2="{pad + bar_px:.1f}" y2="{by:.1f}" '
        f'stroke="{TOKENS["ink_muted"]}" stroke-width="2"/>'
    )
    out.append(
        f'<text x="{pad + bar_px + 10:.1f}" y="{by + 4:.1f}" class="annot-muted">'
        f'{bar_m:,.0f} m</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def coverage_strip(channels: list[tuple[str, np.ndarray, np.ndarray]], *, width: float = 1000.0
                   ) -> str:
    """When each measurement channel could actually speak.

    The gaps are the content. ``docs/03-approach.md`` 3.11 claims no two
    channels share a blind spot; this is where that claim is either visible or
    not, so the silences are drawn as deliberately as the coverage.
    """
    if not channels:
        return ""
    row_h, gap, label_w, value_w = 26.0, 12.0, 248.0, 56.0
    height = len(channels) * (row_h + gap) + 46.0
    # The percentage gets its own gutter. Printed inside the track it collided
    # with the bars and clipped at the frame edge.
    x0, x1 = label_w, width - value_w - 12.0

    out = [
        f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'aria-label="Availability of each measurement channel through the blackout.">'
    ]
    for i, (name, t, valid) in enumerate(channels):
        y = 8.0 + i * (row_h + gap)
        t = np.asarray(t, dtype=float)
        valid = np.asarray(valid, dtype=bool)
        span = max(t[-1] - t[0], 1e-9)

        out.append(
            f'<rect x="{x0:.1f}" y="{y:.1f}" width="{x1 - x0:.1f}" height="{row_h:.1f}" '
            f'rx="3" fill="{TOKENS["panel_raised"]}"/>'
        )
        # Contiguous valid runs, drawn as bars.
        edges = np.flatnonzero(np.diff(valid.astype(int)))
        starts = np.concatenate([[0], edges + 1])
        ends = np.concatenate([edges + 1, [len(valid)]])
        for s, e in zip(starts, ends, strict=False):
            if not valid[s] or e <= s:
                continue
            bx = x0 + (t[s] - t[0]) / span * (x1 - x0)
            bw = max((t[min(e, len(t) - 1)] - t[s]) / span * (x1 - x0), 1.5)
            out.append(
                f'<rect x="{bx:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{row_h:.1f}" '
                f'rx="3" fill="{TOKENS["accent"]}" opacity="0.85"/>'
            )
        pct = float(valid.mean()) * 100.0
        # An empty rounded rect reads as a render bug. A channel that is blind
        # has to say so, in words -- that is the whole posture of the section.
        if pct == 0.0:
            out.append(
                f'<text x="{x0 + 12:.1f}" y="{y + row_h / 2 + 4:.1f}" '
                f'class="annot-muted">withheld for the whole window, by protocol 8.1</text>'
            )
        # Source strings stay ASCII (a mid-dot once corrupted this file through a
        # mis-encoded write); the typographic connector is applied at draw time.
        label = str(name).replace(" - ", " · ")
        out.append(
            f'<text x="{x0 - 14:.1f}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end" '
            f'class="row-label">{_esc(label)}</text>'
        )
        out.append(
            f'<text x="{width - 12:.1f}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end" '
            f'class="row-value">{pct:.0f}%</text>'
        )
    # A strip whose lede says "the gaps are the content" has to say *when*.
    t_all = np.asarray(channels[0][1], dtype=float)
    span_s = max(float(t_all[-1] - t_all[0]), 1e-9)
    y_axis = 8.0 + len(channels) * (row_h + gap) - gap + 7.0
    step = 20.0 if span_s > 45 else 10.0
    tick = 0.0
    while tick <= span_s + 1e-6:
        tx = x0 + (tick / span_s) * (x1 - x0)
        out.append(
            f'<line x1="{tx:.1f}" y1="{y_axis:.1f}" x2="{tx:.1f}" y2="{y_axis + 4:.1f}" '
            f'stroke="{TOKENS["rule_strong"]}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{tx:.1f}" y="{y_axis + 17:.1f}" text-anchor="middle" '
            f'class="tick">{tick:.0f}</text>'
        )
        tick += step
    out.append(
        f'<text x="{x0 - 14:.1f}" y="{y_axis + 17:.1f}" text-anchor="end" '
        f'class="annot-muted">seconds into the blackout</text>'
    )
    out.append("</svg>")
    return "\n".join(out)
