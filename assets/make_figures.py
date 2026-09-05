"""Generate the SETU deck figures. Everything here is computed from the physics in
docs/03-approach.md -- no figure is hand-drawn or decorative.

    python assets/make_figures.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FixedLocator, NullFormatter
import os

NAVY, BLUE = "#14375F", "#0C6DB5"
SAFFRON, GREEN = "#E8761F", "#1B8A4C"
INK, MUTED, RULE = "#14212B", "#5B6E78", "#CDD8DE"
RED = "#B3261E"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "axes.edgecolor": RULE, "axes.linewidth": 0.9,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 8.2, "ytick.labelsize": 8.2,
    "text.color": INK, "axes.labelcolor": MUTED,
    "savefig.dpi": 300, "figure.dpi": 300,
})
HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------- 1
def error_law(path):
    """Horizontal error vs distance during a 1 km / 60 s GNSS outage at 60 km/h."""
    fig, ax = plt.subplots(figsize=(4.15, 2.32))
    d = np.linspace(1, 1000, 500)
    v = 1000 / 60.0                      # 16.67 m/s
    t = d / v

    ins = 0.5 * 0.10 * t**2              # b_a = 0.10 m/s^2, double integration
    vel = 0.031 * d                      # e_v = 3.1 % of distance (published SOTA)
    gate = 0.10 * d                      # SIH ceiling

    # SETU: 1.5 % between anchors, reset to the registration floor at each anchor
    anchors = [(0, 3.0), (380, 5.0), (700, 4.0)]
    segs = []
    for i, (s0, floor) in enumerate(anchors):
        s1 = anchors[i + 1][0] if i + 1 < len(anchors) else 1000
        x = np.linspace(s0, s1, 60)
        segs.append((x, floor + 0.015 * (x - s0)))

    ax.plot(d, gate, ls=(0, (4, 3)), lw=1.1, color="#9AA9B2", zorder=2)
    ax.plot(d, ins, lw=1.9, color=RED, zorder=4)
    ax.plot(d, vel, lw=1.9, color=SAFFRON, zorder=4)
    for x, y in segs:
        ax.plot(x, y, lw=2.2, color=GREEN, zorder=6, solid_capstyle="round")
    for i in range(len(segs) - 1):
        xa, ya = segs[i][0][-1], segs[i][1][-1]
        yb = segs[i + 1][1][0]
        ax.plot([xa, xa], [ya, yb], lw=2.2, color=GREEN, zorder=6)
        ax.plot([xa], [yb], "o", ms=4.0, color=GREEN, mec="white", mew=0.9, zorder=7)
        ax.plot([xa, xa], [0.9, yb], lw=0.7, ls=(0, (2, 2)), color=GREEN, alpha=.55, zorder=1)

    ax.set_yscale("log")
    ax.set_ylim(0.9, 420)
    ax.set_xlim(0, 1000)
    ax.yaxis.set_major_locator(FixedLocator([1, 3, 10, 30, 100, 300]))
    ax.set_yticklabels(["1 m", "3", "10", "30", "100", "300"])
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([0, 200, 400, 600, 800, 1000])
    ax.set_xticklabels(["0", "200", "400", "600", "800", "1000 m"])
    ax.grid(axis="y", color=RULE, lw=0.6, alpha=.85, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    lab = dict(fontsize=8.0, fontweight="bold", va="center")
    ax.text(1000, 250, "pure INS  180 m ", ha="right", color=RED, **lab)
    ax.text(1000, 13.2, "velocity-aided  31 m ", ha="right", color=SAFFRON, **lab)
    ax.text(1000, 2.15, "SETU  8.5 m ", ha="right", color=GREEN, **lab)
    ax.text(30, 120, "SIH ceiling  10 %", fontsize=7.6, color="#7C8B94", fontweight="bold")
    ax.text(390, 1.15, "curvature\nlandmark", fontsize=6.9, color=GREEN, fontweight="bold", va="bottom")
    ax.text(710, 1.15, "magnetic\nanchor", fontsize=6.9, color=GREEN, fontweight="bold", va="bottom")

    ax.set_xlabel("distance travelled during the outage  ·  60 s at 60 km/h",
                  fontsize=7.6, labelpad=3)
    fig.tight_layout(pad=0.25)
    fig.savefig(path, transparent=False, facecolor="white",
                bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", path)


# ----------------------------------------------------------------------------- 2
def spectrogram(path):
    """Synthetic accelerometer spectrogram: axle orders are continuous in v,
    engine orders step down at every upshift. That step is the free label."""
    fig, ax = plt.subplots(figsize=(4.15, 1.72))

    T, F = 20.0, 100.0
    nt, nf = 460, 340
    tv = np.linspace(0, T, nt)
    fv = np.linspace(0, F, nf)
    R_eff = 0.30
    C = 2 * np.pi * R_eff

    # speed profile 8 -> 20 m/s
    kn_t = np.array([0, 5, 8, 11, 14, 17, 20])
    kn_v = np.array([8, 11.75, 14, 15.5, 17, 18.5, 20])
    v = np.interp(tv, kn_t, kn_v)
    f_ax = v / C

    Z = np.random.default_rng(7).normal(0, 1, (nf, nt)) * 0.055
    Z += 0.28 * np.exp(-fv[:, None] / 26.0)          # broadband road/tyre floor

    def ridge(centre, amp, width):
        return amp * np.exp(-0.5 * ((fv[:, None] - centre[None, :]) / width) ** 2)

    for k, amp in [(1, .95), (2, .80), (3, .52), (4, .60), (5, .30),
                   (6, .42), (7, .24), (8, .34), (10, .20), (12, .15)]:
        Z += ridge(k * f_ax, amp, 1.05)

    shifts = [7.0, 14.0]
    ratio = np.where(tv < shifts[0], 7.4, np.where(tv < shifts[1], 5.6, 4.5))
    Z += ridge(v * ratio / C, .78, 1.35)              # engine main order
    Z += ridge(2 * v * ratio / C, .26, 1.6)           # its 2nd harmonic

    cmap = LinearSegmentedColormap.from_list("setu", ["#FFFFFF", "#DCE6EC", "#7FA3BC", NAVY, "#081C30"])
    ax.imshow(Z, origin="lower", aspect="auto", extent=[0, T, 0, F],
              cmap=cmap, vmin=0, vmax=1.05, interpolation="bilinear")

    for s in shifts:
        fa = np.interp(s, tv, v) * (7.4 if s == shifts[0] else 5.6) / C
        fb = np.interp(s, tv, v) * (5.6 if s == shifts[0] else 4.5) / C
        ax.annotate("", xy=(s, fb), xytext=(s, fa),
                    arrowprops=dict(arrowstyle="-|>", color=SAFFRON, lw=1.5,
                                    shrinkA=0, shrinkB=0, mutation_scale=9))
        ax.text(s + 0.45, (fa + fb) / 2, "upshift", fontsize=6.8, color=SAFFRON,
                fontweight="bold", va="center")

    chip = dict(boxstyle="square,pad=0.25", facecolor="white", edgecolor="none", alpha=0.90)
    ax.text(0.5, 92, "axle orders  f = k·v / 2πR   continuous",
            fontsize=7.4, fontweight="bold", color=NAVY, va="center", bbox=chip)
    ax.text(0.5, 82, "engine orders  step at each gear change",
            fontsize=7.4, fontweight="bold", color=SAFFRON, va="center", bbox=chip)

    ax.set_ylim(0, F); ax.set_xlim(0, T)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0", "25", "50", "75", "100 Hz"])
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.set_xticklabels(["0", "5", "10", "15", "20 s"])
    ax.set_xlabel("accelerometer magnitude spectrum  ·  vehicle accelerating 8 → 20 m/s",
                  fontsize=7.4, labelpad=3)
    for sp in ax.spines.values():
        sp.set_color(RULE)
    fig.tight_layout(pad=0.25)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    error_law(os.path.join(HERE, "fig-error-law.png"))
    spectrogram(os.path.join(HERE, "fig-spectrogram.png"))
