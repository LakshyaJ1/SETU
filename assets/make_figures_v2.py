"""Figures for the v2 deck. Sized for their exact placement on the slide, with
type large enough to read at arm's length. Everything is computed, not drawn.

    python assets/make_figures_v2.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter
import os

NAVY, BLUE = "#14375F", "#0C6DB5"
SAFFRON, GREEN = "#E8761F", "#1B8A4C"
INK, MUTED, RULE = "#14212B", "#5B6E78", "#CDD8DE"
RED, GREY = "#B3261E", "#8A99A2"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "axes.edgecolor": RULE, "axes.linewidth": 1.0,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.labelcolor": MUTED,
    "savefig.dpi": 300, "figure.dpi": 300,
})
HERE = os.path.dirname(os.path.abspath(__file__))


def error_law_wide(path):
    """The whole argument in one frame: three error laws over a 1 km blackout."""
    fig, ax = plt.subplots(figsize=(7.0, 2.80))
    d = np.linspace(1, 1000, 600)
    t = d / (1000 / 60.0)

    ins = 0.5 * 0.10 * t ** 2
    vel = 0.031 * d
    gate = 0.10 * d

    anchors = [(0, 3.0), (380, 5.0), (700, 4.0)]
    segs = []
    for i, (s0, floor) in enumerate(anchors):
        s1 = anchors[i + 1][0] if i + 1 < len(anchors) else 1000
        x = np.linspace(s0, s1, 80)
        segs.append((x, floor + 0.015 * (x - s0)))

    ax.plot(d, gate, ls=(0, (5, 4)), lw=1.4, color=GREY, zorder=2)
    ax.plot(d, ins, lw=3.0, color=RED, zorder=4, solid_capstyle="round")
    ax.plot(d, vel, lw=3.0, color=SAFFRON, zorder=4, solid_capstyle="round")
    for x, y in segs:
        ax.plot(x, y, lw=3.4, color=GREEN, zorder=6, solid_capstyle="round")
    for i in range(len(segs) - 1):
        xa, ya = segs[i][0][-1], segs[i][1][-1]
        yb = segs[i + 1][1][0]
        ax.plot([xa, xa], [ya, yb], lw=3.4, color=GREEN, zorder=6)
        ax.plot([xa], [yb], "o", ms=7, color=GREEN, mec="white", mew=1.6, zorder=7)
        ax.plot([xa, xa], [0.95, yb], lw=1.0, ls=(0, (2, 2)), color=GREEN, alpha=.6, zorder=1)

    ax.set_yscale("log")
    ax.set_ylim(0.95, 1100)
    ax.set_xlim(0, 1000)
    ax.yaxis.set_major_locator(FixedLocator([1, 3, 10, 30, 100, 300]))
    ax.set_yticklabels(["1 m", "3", "10", "30", "100", "300"], fontsize=10.5)
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([0, 200, 400, 600, 800, 1000])
    ax.set_xticklabels(["0", "200", "400", "600", "800", "1000 m"], fontsize=10.5)
    ax.grid(axis="y", color=RULE, lw=0.8, alpha=.9, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    # legend lives in the empty upper-left quadrant, clear of every curve
    leg = [(RED, "PURE INERTIAL   180 m", "error grows as t²", 700, 500),
           (SAFFRON, "VELOCITY-AIDED   31 m", "grows with distance — 3.1 %/km", 260, 186),
           (GREEN, "SETU   8.5 m", "bounded by anchors, not by time", 100, 71)]
    for col, t1, t2, ya, yb in leg:
        ax.plot([26, 92], [ya, ya], lw=3.4, color=col, solid_capstyle="round", zorder=9)
        ax.text(108, ya, t1, fontsize=11, fontweight="bold", color=col,
                va="center", zorder=9)
        ax.text(108, yb, t2, fontsize=9.2, color=col, va="center", zorder=9)
    ax.text(985, 140, "SIH ceiling — 10 % of distance", fontsize=9.4,
            fontweight="bold", color=GREY, ha="right", va="center")
    ax.text(392, 1.05, "curvature\nlandmark", fontsize=8.6, color=GREEN,
            fontweight="bold", va="bottom")
    ax.text(712, 1.05, "magnetic\nanchor", fontsize=8.6, color=GREEN,
            fontweight="bold", va="bottom")
    ax.set_xlabel("horizontal error against distance travelled  ·  60 s blackout at 60 km/h",
                  fontsize=10, labelpad=5)

    fig.tight_layout(pad=0.3)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print("wrote", path)


def tiers(path):
    """Drift per km by device class, against the ceiling and the published result."""
    fig, ax = plt.subplots(figsize=(4.30, 1.80))
    rows = [
        ("Published best", 3.1, GREY),
        ("Tier C  10–50 Hz", 2.5, SAFFRON),
        ("Tier B  50–200 Hz", 1.5, BLUE),
        ("Tier A  ≥200 Hz", 0.75, GREEN),
    ]
    ypos = np.arange(len(rows))
    for i, (lab, v, c) in enumerate(rows):
        ax.barh(i, v, height=0.70, color=c, zorder=3)
        ax.text(v + 0.16, i, f"{v} %", va="center", ha="left",
                fontsize=11.5, fontweight="bold", color=c, zorder=4)

    ax.axvline(10, color=RED, lw=1.6, ls=(0, (4, 3)), zorder=2)
    ax.text(10.35, 1.5, "SIH\nceiling\n10 %", va="center", ha="left",
            fontsize=9.2, fontweight="bold", color=RED, linespacing=1.2)

    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.6, color=INK)
    ax.set_xlim(0, 11.4)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xticks([0, 2, 4, 6, 8, 10])
    ax.set_xticklabels(["0", "2", "4", "6", "8", "10 %"], fontsize=9.4)
    ax.grid(axis="x", color=RULE, lw=0.8, zorder=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("drift as a share of distance, per km of blackout",
                  fontsize=9.6, labelpad=4)

    fig.tight_layout(pad=0.3)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print("wrote", path)


def error_law_flat(path):
    """Same three error laws, flattened for a smaller slot. The colour key and the
    reading of it live in the slide text, so the frame carries only the curves."""
    fig, ax = plt.subplots(figsize=(7.0, 1.90))
    d = np.linspace(1, 1000, 600)
    t = d / (1000 / 60.0)

    ins = 0.5 * 0.10 * t ** 2
    vel = 0.031 * d
    gate = 0.10 * d

    anchors = [(0, 3.0), (380, 5.0), (700, 4.0)]
    segs = []
    for i, (s0, floor) in enumerate(anchors):
        s1 = anchors[i + 1][0] if i + 1 < len(anchors) else 1000
        x = np.linspace(s0, s1, 80)
        segs.append((x, floor + 0.015 * (x - s0)))

    ax.plot(d, gate, ls=(0, (5, 4)), lw=1.3, color=GREY, zorder=2)
    ax.plot(d, ins, lw=3.2, color=RED, zorder=4, solid_capstyle="round")
    ax.plot(d, vel, lw=3.2, color=SAFFRON, zorder=4, solid_capstyle="round")
    for x, y in segs:
        ax.plot(x, y, lw=3.6, color=GREEN, zorder=6, solid_capstyle="round")
    for i in range(len(segs) - 1):
        xa, ya = segs[i][0][-1], segs[i][1][-1]
        yb = segs[i + 1][1][0]
        ax.plot([xa, xa], [ya, yb], lw=3.6, color=GREEN, zorder=6)
        ax.plot([xa], [yb], "o", ms=7, color=GREEN, mec="white", mew=1.6, zorder=7)
        ax.plot([xa, xa], [1.02, yb], lw=1.0, ls=(0, (2, 2)), color=GREEN, alpha=.6, zorder=1)

    ax.set_yscale("log")
    ax.set_ylim(1.0, 330)
    ax.set_xlim(0, 1000)
    ax.yaxis.set_major_locator(FixedLocator([1, 10, 100]))
    ax.set_yticklabels(["1 m", "10", "100"], fontsize=10.5)
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([0, 250, 500, 750, 1000])
    ax.set_xticklabels(["0", "250", "500", "750", "1000 m"], fontsize=10.5)
    ax.grid(axis="y", color=RULE, lw=0.8, alpha=.9, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    for yv, txt, col in ((238, "180 m", RED), (20.5, "31 m", SAFFRON),
                         (4.6, "8.5 m", GREEN)):
        ax.text(988, yv, txt, fontsize=11.5, fontweight="bold", color=col,
                ha="right", va="center", zorder=9)
    ax.text(26, 196, "SIH ceiling — 10 % of distance", fontsize=9.4,
            fontweight="bold", color=GREY, va="center")
    ax.text(392, 1.12, "bend matched\nto the map", fontsize=8.4, color=GREEN,
            fontweight="bold", va="bottom")
    ax.text(712, 1.12, "tunnel magnetic\nsignature", fontsize=8.4, color=GREEN,
            fontweight="bold", va="bottom")

    fig.tight_layout(pad=0.25)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    error_law_wide(os.path.join(HERE, "fig-error-law-wide.png"))
    tiers(os.path.join(HERE, "fig-tiers.png"))
    error_law_flat(os.path.join(HERE, "fig-error-law-flat.png"))
