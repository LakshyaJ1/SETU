"""v2 of the SETU submission deck: same six-slide SIH template, redesigned for
single-glance comprehension.

Changes from v1: larger type throughout, prose cut to phrases, one dominant visual
per slide, and slide 3 rebuilt as a three-plane system architecture sized for
population-scale deployment rather than a linear pipeline.

Template chrome (SIH logo, team oval, footer rail, slide numbers, titles) is
untouched; the mandated idea pointers remain as each section's own heading.

    python assets/make_figures_v2.py && python assets/build_deck_v2.py
"""
import os
from pptx import Presentation
from pptx.util import Inches as In, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SIH2026-IDEA-Presentation-Format.pptx")
DST = os.path.join(ROOT, "SETU-SIH2026-Idea-Presentation-v2.pptx")

TEAM = "Sanskari<CODERS>"
MEMBERS = [("Lakshya Jain", "Team Leader"), ("Akshit Jain", ""), ("Veneya Kharkhodi", ""),
           ("Garv Goel", ""), ("Lavish Kumar", ""), ("Aashi Jain", "")]

NAVY = RGBColor(0x14, 0x37, 0x5F)
BLUE = RGBColor(0x0C, 0x6D, 0xB5)
SAFFRON = RGBColor(0xE8, 0x76, 0x1F)
GREEN = RGBColor(0x1B, 0x8A, 0x4C)
RED = RGBColor(0xB3, 0x26, 0x1E)
INK = RGBColor(0x14, 0x21, 0x2B)
MUTED = RGBColor(0x5B, 0x6E, 0x78)
FIELD = RGBColor(0x9A, 0xA9, 0xB2)
RULE = RGBColor(0xCD, 0xD8, 0xDE)
PANEL = RGBColor(0xF3, 0xF7, 0xF9)
PANEL2 = RGBColor(0xE8, 0xEF, 0xF3)
LANE1 = RGBColor(0xFA, 0xFC, 0xFD)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE = RGBColor(0xD6, 0xE3, 0xEC)

SANS, SERIF, MONO = "Arial", "Times New Roman", "Consolas"
TOP, BOT = 1.28, 6.82
L, R = 0.42, 12.91
W = R - L


# ---------------------------------------------------------------- primitives
def rect(sl, x, y, w, h, fill=None, line=None, lw=0.75, shape=MSO_SHAPE.RECTANGLE):
    s = sl.shapes.add_shape(shape, In(x), In(y), In(w), In(h))
    s.shadow.inherit = False
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
    s.text_frame.word_wrap = True
    return s


def line(sl, x1, y1, x2, y2, color=RULE, lw=0.9):
    ln = sl.shapes.add_connector(1, In(x1), In(y1), In(x2), In(y2))
    ln.line.color.rgb = color
    ln.line.width = Pt(lw)
    return ln


def arrow(sl, x, y, w, h, color=RULE, shape=MSO_SHAPE.RIGHT_ARROW):
    s = sl.shapes.add_shape(shape, In(x), In(y), In(w), In(h))
    s.shadow.inherit = False
    s.fill.solid(); s.fill.fore_color.rgb = color
    s.line.fill.background()
    return s


def tb(sl, x, y, w, h, paras, anchor="t", pad=0.05):
    box = sl.shapes.add_textbox(In(x), In(y), In(w), In(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = In(pad)
    tf.margin_top = tf.margin_bottom = In(0.01)
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE,
                          "b": MSO_ANCHOR.BOTTOM}[anchor]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if p.get("align"):
            para.alignment = p["align"]
        if p.get("sb") is not None:
            para.space_before = Pt(p["sb"])
        if p.get("sa") is not None:
            para.space_after = Pt(p["sa"])
        if p.get("line"):
            para.line_spacing = p["line"]
        for spec in p["runs"]:
            r = para.add_run(); r.text = spec[0]
            r.font.size = Pt(spec[1]); r.font.bold = spec[2]
            r.font.color.rgb = spec[3]
            r.font.name = spec[4] if len(spec) > 4 else SANS
    return box


def picture(sl, x, y, w, img):
    iw, ih = Image.open(img).size
    h = w * ih / iw
    sl.shapes.add_picture(img, In(x), In(y), In(w), In(h))
    return y + h


def heading(sl, x, y, w, text, size=13.5):
    tb(sl, x, y, w, 0.30, [{"runs": [(text, size, True, NAVY)], "line": 0.94}], pad=0.0)
    line(sl, x, y + 0.29, x + w, y + 0.29, NAVY, 1.5)
    return y + 0.42


def kill(sl, *names):
    for sh in list(sl.shapes):
        if sh.name in names:
            sh._element.getparent().remove(sh._element)


def set_title(sl, text, size=None):
    for sh in sl.shapes:
        if sh.name.startswith("Title") and sh.has_text_frame:
            p = sh.text_frame.paragraphs[0]
            if p.runs:
                p.runs[0].text = text
                if size:
                    p.runs[0].font.size = Pt(size)
                for extra in p.runs[1:]:
                    extra.text = ""
            return


def set_oval(sl):
    """The template's team badge, filled in."""
    for sh in sl.shapes:
        if sh.name.startswith("Oval") and sh.has_text_frame:
            tf = sh.text_frame
            tf.word_wrap = True
            for p in list(tf.paragraphs)[1:]:
                p._p.getparent().remove(p._p)
            p0 = tf.paragraphs[0]
            for r in list(p0.runs):
                r._r.getparent().remove(r._r)
            p0.alignment = PP_ALIGN.CENTER
            p0.line_spacing = 0.92
            r = p0.add_run(); r.text = "Sanskari"
            r.font.size = Pt(10); r.font.bold = True
            r.font.color.rgb = NAVY; r.font.name = SANS
            p1 = tf.add_paragraph()
            p1.alignment = PP_ALIGN.CENTER
            p1.line_spacing = 0.92
            r = p1.add_run(); r.text = "<CODERS>"
            r.font.size = Pt(10); r.font.bold = True
            r.font.color.rgb = BLUE; r.font.name = MONO
            return


# =============================================================== SLIDE 1
def slide1(sl):
    kill(sl, "TextBox 9")
    for sh in sl.shapes:
        if sh.name.startswith("Subtitle") and sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    r.text = ""
            tf = sh.text_frame
            p = tf.paragraphs[1] if len(tf.paragraphs) > 1 else tf.paragraphs[0]
            r = p.add_run(); r.text = "SETU · INTELLIGENT DEAD RECKONING"
            r.font.size = Pt(23); r.font.bold = True
            r.font.color.rgb = NAVY; r.font.name = SERIF

    F = 19.0
    blank = ("____________", F, False, FIELD)
    rows = [
        [("Problem Statement ID –  ", F, True, NAVY), blank],
        [("Problem Statement Title-  ", F, True, NAVY),
         ("AI-ML based Intelligent Dead Reckoning system for seamless navigation",
          F, False, INK)],
        [("Theme-  ", F, True, NAVY), blank],
        [("PS Category-  ", F, True, NAVY), ("Software", F, False, INK)],
        [("Team ID-  ", F, True, NAVY), blank],
        [("Team Name (Registered on portal)-  ", F, True, NAVY),
         (TEAM, F, False, INK)],
    ]
    tb(sl, L, 2.10, 6.70, 4.60,
       [{"runs": r, "sa": 9, "line": 1.0} for r in rows], pad=0.0)

    # identity card, filling the dead space under the artwork
    cx, cy, cw, ch = 7.12, 5.60, 5.79, 1.26
    rect(sl, cx, cy, cw, ch, fill=WHITE, line=NAVY, lw=1.25)
    tb(sl, cx, cy + 0.06, cw - 1.72, ch - 0.12, [
        {"runs": [("Seamless Egomotion Tracking under Unavailable-GNSS", 10.5, True, NAVY)],
         "sa": 3, "line": 1.0},
        {"runs": [("Lane-level position through tunnels, underpasses, basement parking and "
                   "urban canyons — from a smartphone IMU alone.", 9.6, False, INK)],
         "line": 1.05}], pad=0.12)
    line(sl, cx + cw - 1.74, cy + 0.16, cx + cw - 1.74, cy + ch - 0.16, RULE, 1.0)
    tb(sl, cx + cw - 1.70, cy + 0.06, 1.62, ch - 0.12, [
        {"runs": [("≈1%", 28, True, GREEN)], "align": PP_ALIGN.CENTER, "sa": 0, "line": 0.92},
        {"runs": [("drift per km, against\na 10 % ceiling", 8.6, False, MUTED)],
         "align": PP_ALIGN.CENTER, "line": 1.04}], anchor="m", pad=0.03)

    # team roster on the footer rail
    rect(sl, 0, 6.95, 13.333, 0.55, fill=BLUE)
    runs = [("TEAM  ", 11, True, PALE), (TEAM, 12, True, WHITE), ("      ", 11, False, WHITE)]
    for i, (name, role) in enumerate(MEMBERS):
        if i:
            runs.append(("  ·  ", 10.5, False, PALE))
        runs.append((name, 10.5, True, WHITE))
        if role:
            runs.append((" (" + role + ")", 10.5, False, PALE))
    tb(sl, 0.40, 6.95, 12.53, 0.55,
       [{"runs": runs, "align": PP_ALIGN.CENTER, "line": 1.0}], anchor="m")


# =============================================================== SLIDE 2
def slide2(sl):
    kill(sl, "TextBox 8"); set_oval(sl)
    set_title(sl, "SETU — NAVIGATION WITHOUT GNSS", 32)

    tb(sl, L, 1.30, W, 0.66, [{"runs": [
        ("Everyone integrates acceleration twice, so error grows as t². ", 19, True, NAVY),
        ("SETU asks how far along this road am I — and answers with measurements that never "
         "accumulate.", 19, False, INK)], "line": 1.06}], pad=0.0)
    line(sl, L, 2.00, R, 2.00, RULE, 1.0)

    LW, RX, RW = 4.60, 5.26, 7.65

    # ---- the engine, as a pipeline of eight modules
    heading(sl, L, 2.10, LW, "Detailed explanation of the proposed solution", 12.5)
    mods = [
        ("ACE", BLUE, "solves the phone→vehicle mount, online"),
        ("MSVR", BLUE, "classifies motion, mount and road shock"),
        ("SVO", GREEN, "ground speed from axle harmonics"),
        ("CTS", GREEN, "absolute speed out of every turn"),
        ("CSA", SAFFRON, "arc length from the map's own shape"),
        ("EFA", SAFFRON, "magnetic, baro and radio anchors"),
        ("IAF", NAVY, "invariant EKF in a road-graph filter"),
        ("GQM", NAVY, "per-satellite GNSS trust, not a switch"),
    ]
    y0, pitch, ch = 2.52, 0.33, 0.30
    line(sl, L + 0.31, y0 + 0.15, L + 0.31, y0 + pitch * 7 + 0.15, RULE, 1.1)
    for i, (tag, col, txt) in enumerate(mods):
        yy = y0 + i * pitch
        rect(sl, L, yy, 0.62, ch, fill=WHITE, line=col, lw=1.1)
        tb(sl, L, yy, 0.62, ch, [{"runs": [(tag, 9.6, True, col)],
                                  "align": PP_ALIGN.CENTER}], anchor="m", pad=0.01)
        tb(sl, L + 0.70, yy, LW - 0.70, ch,
           [{"runs": [(txt, 10.4, False, INK)], "line": 1.0}], anchor="m", pad=0.03)

    rect(sl, L, 5.28, LW, 0.50, fill=PANEL, line=RULE)
    tb(sl, L, 5.28, LW, 0.50, [{"runs": [
        ("3.6 MB", 11, True, NAVY, MONO), ("  models    ", 9, False, MUTED),
        ("2.7 ms", 11, True, NAVY, MONO), ("  per tick    ", 9, False, MUTED),
        ("10 Hz", 11, True, NAVY, MONO), ("  phone    ", 9, False, MUTED),
        ("200 Hz", 11, True, NAVY, MONO), ("  edge", 9, False, MUTED)],
        "align": PP_ALIGN.CENTER, "line": 1.0}], anchor="m")

    # ---- the hero visual
    heading(sl, RX, 2.10, RW, "How it addresses the problem", 12.5)
    b = picture(sl, RX, 2.52, RW, os.path.join(HERE, "fig-error-law-wide.png"))
    tb(sl, RX, b + 0.04, RW, 0.26, [{"runs": [
        ("Integration is demoted to interpolating between fixes. Every anchor crossed resets "
         "the error, so drift is bounded by anchor spacing, not by elapsed time.",
         8.8, False, MUTED)], "line": 1.0}], pad=0.0)

    # ---- what is new
    heading(sl, L, 5.92, W, "Innovation and uniqueness of the solution", 12.5)
    nov = [
        ("N1", GREEN, "Speed from frequency", "not integration — nothing accumulates"),
        ("N2", SAFFRON, "Two-wheeler lean physics", "v = g·sinφ / ωz; omitting cosφ costs 4 %"),
        ("N3", BLUE, "Scale-free map registration", "prior shape-matching needs an odometer"),
        ("N4", NAVY, "CAN wheel speeds as teacher", "training-only; far better than GPS labels"),
        ("N5", RED, "Learned σ and Q in one filter", "multi-hypothesis over the road graph"),
    ]
    cw = (W - 4 * 0.12) / 5
    for i, (tag, col, head, note) in enumerate(nov):
        gx = L + i * (cw + 0.12)
        rect(sl, gx, 6.26, cw, 0.56, fill=PANEL, line=RULE)
        tb(sl, gx, 6.28, cw, 0.52, [
            {"runs": [(tag + "  ", 9.6, True, col), (head, 9.6, True, INK)],
             "sa": 1, "line": 1.0},
            {"runs": [(note, 8.4, False, MUTED)], "line": 1.0}], pad=0.09)


# =============================================================== SLIDE 3
def slide3(sl):
    kill(sl, "TextBox 8"); set_oval(sl)
    set_title(sl, "TECHNICAL APPROACH")

    heading(sl, L, TOP, W, "Methodology and process for implementation")

    GX, GW = L, 1.16                 # lane label gutter
    NX = GX + GW + 0.10              # nodes start
    NW = R - NX                      # 11.23

    lanes = [
        (1.70, 1.86, "CLIENT", "RUNTIME", "offline", "zero network calls", GREEN, NAVY, LANE1, 1.5),
        (3.72, 0.86, "SYNC", "PLANE", "out-of-band", "async, never blocking", BLUE, RULE, PANEL, 0.9),
        (4.74, 1.08, "CLOUD", "PLANE", "batch", "region-sharded", MUTED, RULE, PANEL, 0.9),
    ]
    for ly, lh, n1, n2, s1, s2, scol, bcol, fillc, blw in lanes:
        rect(sl, GX, ly, W, lh, fill=fillc, line=bcol, lw=blw)
        tb(sl, GX, ly, GW, lh, [
            {"runs": [(n1, 10.5, True, NAVY)], "sa": 0, "line": 0.92},
            {"runs": [(n2, 10.5, True, NAVY)], "sa": 3, "line": 0.92},
            {"runs": [(s1, 8.0, True, scol)], "sa": 0, "line": 0.95},
            {"runs": [(s2, 8.0, False, MUTED)], "line": 0.95},
        ], anchor="m", pad=0.09)
        line(sl, GX + GW, ly + 0.08, GX + GW, ly + lh - 0.08, RULE, 0.9)

    # ---------------- lane 1: the on-device pipeline
    groups = [
        (NX, 1.70, "SENSE", [
            ("IMU", "200–400 Hz"), ("GNSS raw", "NavIC L5"),
            ("Baro", "Magnetometer"), ("External IMU", "MEMS / FOG"),
        ]),
        (3.64, 1.70, "CONDITION", [
            ("STFT", "harmonic ridge"), ("Notch", "engine order"),
            ("Shock", "pothole reject"), ("ACE", "mount solve"),
        ]),
        (5.60, 3.29, "OBSERVE", [
            ("SVO", "spectral speed"), ("CTS", "turn speed"),
            ("CSA", "map arc length"), ("EFA", "field anchors"),
            ("NHC", "zero side-slip"), ("GQM", "sat trust"),
        ]),
        (9.15, 1.85, "FUSE", [
            ("RI-EKF", "SE₂(3)"), ("learned σ", "per measurement"),
            ("learned Q", "transformer"), ("RB-PF", "road graph"),
        ]),
        (11.26, 1.57, "DELIVER", [
            ("10 Hz", "phone pose"), ("200 Hz", "edge pose"),
            ("Lane-level", "+ tube"), ("API", "gRPC · NMEA"),
        ]),
    ]
    hy, cy0 = 1.76, 2.04
    for gx, gw, name, chips in groups:
        rect(sl, gx, hy, gw, 0.24, fill=NAVY)
        tb(sl, gx, hy, gw, 0.24, [{"runs": [(name, 8.6, True, WHITE)],
                                   "align": PP_ALIGN.CENTER}], anchor="m", pad=0.02)
        if name == "OBSERVE":
            sub = (gw - 0.10) / 2
            for j, (a, b) in enumerate(chips):
                px = gx + (j % 2) * (sub + 0.10)
                py = cy0 + (j // 2) * 0.42
                rect(sl, px, py, sub, 0.36, fill=WHITE, line=RULE)
                tb(sl, px, py, sub, 0.36, [
                    {"runs": [(a, 9.0, True, NAVY)], "sa": 0, "line": 0.94},
                    {"runs": [(b, 7.8, False, MUTED)], "line": 0.94}],
                   anchor="m", pad=0.05)
        else:
            for j, (a, b) in enumerate(chips):
                py = cy0 + j * 0.34
                rect(sl, gx, py, gw, 0.29, fill=WHITE, line=RULE)
                tb(sl, gx, py, gw, 0.29, [{"runs": [
                    (a, 8.8, True, NAVY), ("   " + b, 7.8, False, MUTED)],
                    "line": 0.95}], anchor="m", pad=0.06)

    for ax in (3.40, 5.36, 8.91, 11.02):
        arrow(sl, ax, 2.67, 0.22, 0.20, BLUE)

    # ---------------- lane 2: distribution down, contribution up
    HA, HAW, HB, HBW = NX, 5.30, 7.30, 5.61
    halves = [
        (HA, HAW, "DISTRIBUTION", "signed, immutable, versioned bundles — installed offline",
         BLUE, [("Model registry", ""), ("Map / tile CDN", ""), ("Config & flags", "")]),
        (HB, HBW, "CONTRIBUTION", "opt-in · ~1 KB per edge · signatures only, never trajectories",
         GREEN, [("API gateway", ""), ("Stream queue", ""), ("k-anon aggregator", "")]),
    ]
    for hx, hw, hname, hnote, hcol, nodes in halves:
        tb(sl, hx, 3.78, hw, 0.20, [{"runs": [
            (hname, 8.8, True, hcol), ("     " + hnote, 8.0, False, MUTED)],
            "line": 0.95}], pad=0.0)
        nw = (hw - 0.20) / 3
        for j, (nm, _) in enumerate(nodes):
            nx = hx + j * (nw + 0.10)
            rect(sl, nx, 4.02, nw, 0.44, fill=WHITE, line=hcol, lw=1.0)
            tb(sl, nx, 4.02, nw, 0.44, [{"runs": [(nm, 9.0, True, NAVY)],
                                         "align": PP_ALIGN.CENTER, "line": 0.96}],
               anchor="m", pad=0.04)

    arrow(sl, 3.28, 3.56, 0.24, 0.16, BLUE, MSO_SHAPE.UP_ARROW)
    arrow(sl, 3.28, 4.58, 0.24, 0.16, BLUE, MSO_SHAPE.UP_ARROW)
    arrow(sl, 10.16, 3.56, 0.24, 0.16, GREEN, MSO_SHAPE.DOWN_ARROW)
    arrow(sl, 10.16, 4.58, 0.24, 0.16, GREEN, MSO_SHAPE.DOWN_ARROW)

    # ---------------- lane 3: map build and learning
    tb(sl, HA, 4.80, HAW, 0.20, [{"runs": [
        ("MAP BUILD", 8.8, True, NAVY), ("     per region, independently", 8.0, False, MUTED)],
        "line": 0.95}], pad=0.0)
    mb = [("OSM extract", ""), ("Graph + κ(s) LUT", ""), ("DEM · PMTiles", "")]
    nw = (HAW - 0.20) / 3
    for j, (nm, _) in enumerate(mb):
        nx = HA + j * (nw + 0.10)
        rect(sl, nx, 5.02, nw, 0.42, fill=WHITE, line=NAVY, lw=1.0)
        tb(sl, nx, 5.02, nw, 0.42, [{"runs": [(nm, 8.8, True, NAVY)],
                                     "align": PP_ALIGN.CENTER, "line": 0.96}],
           anchor="m", pad=0.03)
        if j < 2:
            arrow(sl, nx + nw - 0.005, 5.14, 0.11, 0.18, RULE)

    tb(sl, HB, 4.80, HBW, 0.20, [{"runs": [
        ("LEARNING", 8.8, True, NAVY), ("     nightly retrain, gated on the benchmark",
                                        8.0, False, MUTED)], "line": 0.95}], pad=0.0)
    lr = [("Data lake", ""), ("Training cluster", ""), ("Eval gate", ""), ("Telemetry & KPI", "")]
    nw2 = (HBW - 0.30) / 4
    for j, (nm, _) in enumerate(lr):
        nx = HB + j * (nw2 + 0.10)
        rect(sl, nx, 5.02, nw2, 0.42, fill=WHITE, line=NAVY, lw=1.0)
        tb(sl, nx, 5.02, nw2, 0.42, [{"runs": [(nm, 8.8, True, NAVY)],
                                      "align": PP_ALIGN.CENTER, "line": 0.96}],
           anchor="m", pad=0.03)
        if j < 3:
            arrow(sl, nx + nw2 - 0.005, 5.14, 0.11, 0.18, RULE)

    tb(sl, NX, 5.48, NW, 0.28, [{"runs": [
        ("SCALES BY SHARDING, NOT BY CAPACITY", 8.4, True, NAVY),
        ("     zero runtime API calls, so device count adds no serving load  ·  "
         "≤250 MB per region  ·  immutable CDN bundles  ·  contribution ~1 KB per edge",
         8.2, False, INK)], "line": 1.0}],
       anchor="m", pad=0.0)

    # ---------------- technologies
    heading(sl, L, 5.90, W, "Technologies to be used")
    tw = (W - 4 * 0.10) / 5
    groups2 = [
        ("Training", "PyTorch · Lightning · Hydra · MLflow · masked-IMU pretraining"),
        ("On-device", "LiteRT + XNNPACK · ExecuTorch · int8 QAT · 3.6 MB total"),
        ("Engine", "C++20 · Eigen · SE₂(3) Lie · FlatBuffers · GTest replay"),
        ("Mobile", "Kotlin · Compose · MapLibre + PMTiles · SensorDirectChannel"),
        ("Edge & maps", "aarch64 · gRPC / NMEA / ROS 2 · osmium · CartoDEM"),
    ]
    for i, (name, body) in enumerate(groups2):
        gx = L + i * (tw + 0.10)
        rect(sl, gx, 6.28, tw, 0.54, fill=PANEL, line=RULE)
        tb(sl, gx, 6.30, tw, 0.50, [
            {"runs": [(name, 9.0, True, NAVY)], "sa": 1, "line": 0.96},
            {"runs": [(body, 8.2, False, INK)], "line": 1.0}], pad=0.08)


# =============================================================== SLIDE 4
def slide4(sl):
    kill(sl, "TextBox 8"); set_oval(sl)
    set_title(sl, "FEASIBILITY AND VIABILITY")

    LW = 4.34
    y = heading(sl, L, TOP, LW, "Analysis of the feasibility of the idea")
    feas = [
        ("Data already in hand", "IO-VNBD: 5,700 km, phone IMU and CAN bus recorded together"),
        ("Core physics is closed-form", "v = a_lat/Ω and f = v/2πR are algebra; only residuals learn"),
        ("Fits today's phones", "3.6 MB int8, 2.7 ms per tick, CPU only — no NPU needed"),
        ("Sensors already present", "IMU, magnetometer, barometer, raw GNSS with NavIC L5"),
        ("Maps fit offline", "≤250 MB per metro region, no connectivity at runtime"),
        ("Nothing to buy or fit", "no dongle, no encoder, no roadside infrastructure"),
    ]
    for i, (claim, ev) in enumerate(feas):
        yy = y + i * 0.44
        tb(sl, L, yy, LW, 0.42, [
            {"runs": [(claim, 10.4, True, NAVY)], "sa": 0, "line": 0.98},
            {"runs": [(ev, 9.2, False, INK)], "line": 1.0}], pad=0.0)

    b = picture(sl, L, 4.42, LW, os.path.join(HERE, "fig-tiers.png"))
    tb(sl, L, b + 0.04, LW, 0.30, [{"runs": [
        ("Every device class clears the ceiling. IO-VNBD's 10 Hz stream is Tier C — so that is "
         "how we report it.", 8.6, False, MUTED)], "line": 1.0}], pad=0.0)

    # risks
    tx, tw_ = 5.00, 7.91
    rows = [
        ("CSA ambiguous on featureless or badly-mapped roads", "High", RED,
         "Landmark saliency scoring · top-k hypotheses in the particle filter · honest σ. "
         "Falls back to classical HMM map matching."),
        ("Axle harmonics weak — smooth road, quiet EV, soft mount", "Medium", SAFFRON,
         "Mount-quality gate · summation over 8+ orders · learned σ down-weights it. "
         "Falls back to Tier B."),
        ("IO-VNBD phone stream is 10 Hz, so cannot validate SVO", "Known", BLUE,
         "Declared as capability tiers. SVO validated on self-collected 400 Hz logs."),
        ("No two-wheeler data in IO-VNBD — four cars, no Indian roads", "Known", BLUE,
         "Lean relation imposed as a physics loss, so few samples suffice. Dedicated collection."),
        ("Sensor rate throttled below 200 Hz on some devices", "Medium", SAFFRON,
         "Tier detected at runtime · SensorDirectChannel · verified on three device classes."),
        ("Uneven OpenStreetMap geometry on Indian roads", "Medium", SAFFRON,
         "Covariance scaled by OSM confidence · explicit off-road particle · provider adapter."),
    ]
    shp = sl.shapes.add_table(len(rows) + 1, 3, In(tx), In(TOP), In(tw_), In(4.70))
    t = shp.table
    t.first_row = False; t.horz_banding = False
    for c, wd in zip(t.columns, (2.72, 0.82, 4.37)):
        c.width = In(wd)
    t.rows[0].height = In(0.40)
    for i in range(1, len(rows) + 1):
        t.rows[i].height = In(0.716)
    for j, htxt in enumerate(["Potential challenges and risks", "Severity",
                              "Strategies for overcoming these challenges"]):
        cell = t.cell(0, j)
        cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
        cell.margin_left = cell.margin_right = In(0.07)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        r = p.add_run(); r.text = htxt
        r.font.size = Pt(9.8); r.font.bold = True
        r.font.color.rgb = WHITE; r.font.name = SANS
        if j == 1:
            p.alignment = PP_ALIGN.CENTER
    for i, (risk, sev, sev_c, strat) in enumerate(rows, start=1):
        for j, val in enumerate((risk, sev, strat)):
            cell = t.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL if i % 2 else WHITE
            cell.margin_left = cell.margin_right = In(0.07)
            cell.margin_top = cell.margin_bottom = In(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.line_spacing = 1.0
            r = p.add_run(); r.text = val
            r.font.name = SANS
            if j == 0:
                r.font.size = Pt(9.4); r.font.bold = True; r.font.color.rgb = NAVY
            elif j == 1:
                r.font.size = Pt(9.2); r.font.bold = True; r.font.color.rgb = sev_c
                p.alignment = PP_ALIGN.CENTER
            else:
                r.font.size = Pt(9.0); r.font.bold = False; r.font.color.rgb = INK

    rect(sl, tx, 6.18, tw_, 0.62, fill=PANEL2, line=NAVY, lw=1.0)
    tb(sl, tx, 6.18, tw_, 0.62, [{"runs": [
        ("Fallback ladder", 10, True, NAVY),
        ("     lose CSA → HMM map matching  ·  lose SVO → Tier B  ·  lose both → INS + NHC + "
         "ZUPT, which already sits inside the 10 % gate. No single failure leaves us with "
         "nothing to demonstrate.", 9.2, False, INK)], "line": 1.0}], anchor="m", pad=0.12)


# =============================================================== SLIDE 5
def slide5(sl):
    kill(sl, "TextBox 8"); set_oval(sl)
    set_title(sl, "IMPACT AND BENEFITS")

    LW = 5.10
    y = heading(sl, L, TOP, LW, "Potential impact on the target audience")
    aud = [
        ("Delivery and quick-commerce riders",
         "the next turn is announced before the exit, not after it"),
        ("Logistics and fleet operators",
         "mileage, ETA and proof of delivery survive the gap — no dongle"),
        ("Ride-hailing drivers and riders",
         "no frozen or teleporting car; pickups on the correct side"),
        ("Emergency responders",
         "a live position underground, where dispatch loses them today"),
        ("Two-wheeler riders",
         "India's largest vehicle class, finally with lean-aware physics"),
        ("Defence and critical logistics",
         "self-contained; degrades gracefully under jamming or spoofing"),
    ]
    for i, (who, what) in enumerate(aud):
        yy = y + i * 0.52
        tb(sl, L, yy, LW, 0.50, [
            {"runs": [(who, 11, True, NAVY)], "sa": 0, "line": 0.98},
            {"runs": [(what, 9.8, False, INK)], "line": 1.0}], pad=0.0)

    sy = 4.90
    rect(sl, L, sy, LW, 1.92, fill=PANEL, line=RULE)
    tb(sl, L, sy + 0.05, LW, 1.82, [
        {"runs": [("Where it matters most", 11, True, NAVY)], "sa": 5, "line": 1.0},
        {"runs": [("Long tunnels and metro underpasses", 9.6, True, INK),
                  ("   the road is one-dimensional, so the map carries it",
                   9.0, False, MUTED)], "sa": 4, "line": 1.0},
        {"runs": [("Multi-level parking", 9.6, True, INK),
                  ("   helical ramps are unique signatures; the barometer gives the floor",
                   9.0, False, MUTED)], "sa": 4, "line": 1.0},
        {"runs": [("Dense urban canyons", 9.6, True, INK),
                  ("   position unusable, but Doppler velocity survives on 3–4 satellites",
                   9.0, False, MUTED)], "sa": 4, "line": 1.0},
        {"runs": [("Forested and valley highways", 9.6, True, INK),
                  ("   partial GNSS, absorbed by the trust ramp with no mode switch",
                   9.0, False, MUTED)], "sa": 0, "line": 1.0},
    ], pad=0.11)

    bx = 5.76
    bwid = W - (bx - L)
    bw = (bwid - 0.22) / 2
    y2 = heading(sl, bx, TOP, bwid,
                 "Benefits of the solution (social, economic, environmental, etc.)")
    blocks = [
        ("Social", GREEN,
         "A correct instruction on time means fewer glances at the screen when a rider can least "
         "afford one. Emergency crews stay locatable underground. Accurate navigation stops being "
         "a feature of expensive cars."),
        ("Economic", BLUE,
         "Zero marginal hardware — it runs on phones riders already own. No dongle per vehicle, "
         "no factory INS, no leaky-feeder per tunnel. Fewer missed exits and failed deliveries "
         "on the same fleet."),
        ("Environmental", SAFFRON,
         "A missed exit is wasted kilometres, fuel and emissions; removing the cause removes all "
         "three. Entirely on-device, so no roadside infrastructure is built, powered or "
         "maintained."),
        ("Strategic", NAVY,
         "Jamming- and spoofing-resilient by construction, since every channel is self-contained. "
         "Uses NavIC L5 where Indian devices expose it, runs fully offline, keeps data on the "
         "phone."),
    ]
    for i, (name, col, body) in enumerate(blocks):
        gx = bx + (i % 2) * (bw + 0.22)
        gy = y2 + (i // 2) * 1.38
        rect(sl, gx, gy, bw, 1.22, fill=PANEL, line=RULE)
        tb(sl, gx, gy + 0.05, bw, 1.12, [
            {"runs": [(name, 11.5, True, col)], "sa": 4, "line": 1.0},
            {"runs": [(body, 9.4, False, INK)], "line": 1.04}], pad=0.11)

    qy = y2 + 2.90
    cells = [
        ("Pure inertial", "180 m", RED, "½·b·t² — a block away after one minute"),
        ("Best published", "31 m", SAFFRON, "3.1 % per km, INS + NHC in a real tunnel"),
        ("SETU target", "8–15 m", GREEN, "0.8–1.5 % per km, anchored to map and field"),
    ]
    cw = (bwid - 2 * 0.16) / 3
    for i, (label, num, col, note) in enumerate(cells):
        gx = bx + i * (cw + 0.16)
        rect(sl, gx, qy, cw, 1.46, fill=WHITE, line=col, lw=1.4)
        tb(sl, gx, qy + 0.07, cw, 1.32, [
            {"runs": [(label, 9.2, True, MUTED)], "sa": 1, "line": 1.0},
            {"runs": [(num, 31, True, col)], "sa": 3, "line": 0.90},
            {"runs": [(note, 8.6, False, INK)], "line": 1.02}], pad=0.10)
    tb(sl, bx, qy + 1.52, bwid, 0.26, [{"runs": [
        ("Horizontal drift over a 1 km blackout at 60 km/h. The SIH ceiling is 10 % — 100 m.",
         9.0, False, MUTED)], "align": PP_ALIGN.CENTER, "line": 1.0}], pad=0.0)

    rect(sl, bx, qy + 1.86, bwid, 0.52, fill=PANEL2, line=NAVY, lw=1.0)
    tb(sl, bx, qy + 1.86, bwid, 0.52, [{"runs": [
        ("Reach", 10, True, NAVY),
        ("     any Android phone already on the dashboard — no purchase, no fitting, no "
         "connectivity. The same engine serves a FOG-grade edge unit at 200 Hz.",
         9.2, False, INK)], "line": 1.0}], anchor="m", pad=0.12)


# =============================================================== SLIDE 6
def slide6(sl):
    kill(sl, "TextBox 8"); set_oval(sl)
    set_title(sl, "RESEARCH AND REFERENCES")

    heading(sl, L, TOP, W, "Details / Links of the reference and research work")

    G = [
        ("Dataset and benchmark", [
            ("IO-VNBD: Inertial & Odometry Benchmark Dataset",
             "Data in Brief 35:106885, 2021 · github.com/onyekpeu/IO-VNBD · arXiv:2005.01701"),
            ("WhONet: Wheel Odometry Neural Network",
             "Eng. Appl. of AI, 2021 · arXiv:2104.02581 — our privileged upper bound"),
            ("R-WhONet: recalibration by transfer learning",
             "arXiv:2209.05877 — evidence of cross-vehicle domain shift"),
        ]),
        ("Learned inertial odometry", [
            ("Deep Learning for Inertial Positioning: A Survey",
             "Chen & Pan · IEEE T-ITS, 2024 · arXiv:2303.03757"),
            ("Inertial Navigation Meets Deep Learning",
             "Cohen & Klein · 2024 · arXiv:2307.00014"),
            ("AI-IMU Dead-Reckoning — invariant EKF",
             "Brossard, Barrau & Bonnabel · IEEE T-IV, 2020 · arXiv:1904.06064"),
            ("TLIO: Tight Learned Inertial Odometry",
             "Liu et al. · IEEE RA-L, 2020 · arXiv:2007.01867 — learned covariance"),
            ("OdoNet: untethered speed aiding",
             "arXiv:2109.03091 · 68 % error reduction over NHC alone"),
            ("CarSpeedNet: accelerometer-only speed",
             "arXiv:2401.07468 · <0.72 m/s ≈ 4.3 % — the accuracy to beat"),
        ]),
        ("Learned and adaptive fusion", [
            ("KalmanNet: NN-aided Kalman filtering",
             "Revach, Shlezinger, van Sloun & Eldar · IEEE TSP, 2022"),
            ("A-KIT: Adaptive Kalman-Informed Transformer",
             "arXiv:2401.09987 · github.com/ansfl/A-KIT — learned process noise"),
            ("PiDR: Physics-Informed Inertial Dead Reckoning",
             "Sahoo & Klein · 2026 · arXiv:2601.03040"),
            ("Differentiable particle filters, semi-supervised",
             "arXiv:2011.05748 — end-to-end learning with algorithmic priors"),
        ]),
        ("Map matching and constraints", [
            ("Hidden Markov Map Matching",
             "Newson & Krumm · ACM SIGSPATIAL, 2009 — the baseline"),
            ("Heading–length sequence matching",
             "arXiv:2005.13704 — nearest prior art to CSA; needs a known speed"),
            ("Map-aided dead reckoning from OBD speed",
             "arXiv:1611.07910"),
            ("Lever-arm accuracy of the non-holonomic constraint",
             "Zhang & Hu · IEEE TVT, 2020"),
            ("NHC-assisted GNSS/SINS with motion-state CNN",
             "GPS Solutions, 2023 · doi 10.1007/s10291-023-01483-9"),
        ]),
        ("Spectral speed and field anchors", [
            ("Vehicle Speed Tracking Using Chassis Vibrations",
             "Linköping University, 2016 — axle-order tracking, motivates tunnels"),
            ("Accelerometer-based wheel odometer",
             "Sensors, 2021 · PMC7918720"),
            ("Magnetic positioning in a long tunnel",
             "Applied Sciences 11(24):11641, 2021"),
            ("Vehicle positioning in tunnels: a review",
             "Complex & Intelligent Systems, 2025"),
            ("Barometric floor detection on smartphones",
             "Sensors, 2015 · PMC4431287 — basis for the parking-level anchor"),
        ]),
        ("GNSS integrity and platform", [
            ("Vehicle positioning underground using a smartphone",
             "ISPRS Archives XLVI-3/W1, 2022 — the 3.1 %/km reference"),
            ("GNSS multipath detection by machine learning",
             "Hsu · IEEE ITSC, 2017"),
            ("Android GnssMeasurement HAL — raw observables",
             "source.android.com · pseudorange, Doppler, C/N₀, AGC"),
            ("u-blox Untethered Dead Reckoning (UDR)",
             "u-blox.com — the closest commercial analogue, on dedicated hardware"),
        ]),
    ]
    C3 = (W - 2 * 0.24) / 3
    for k, groups in enumerate(([G[0], G[1]], [G[2], G[3]], [G[4], G[5]])):
        x = L + k * (C3 + 0.24)
        paras = []
        for gi, (gname, refs) in enumerate(groups):
            paras.append({"runs": [(gname.upper(), 9.8, True, BLUE)],
                          "sb": 0 if gi == 0 else 13, "sa": 5, "line": 1.0})
            for title, src in refs:
                paras.append({"runs": [(title, 9.4, True, INK)], "sa": 0, "line": 1.0})
                paras.append({"runs": [(src, 8.6, False, MUTED)], "sa": 6, "line": 1.0})
        tb(sl, x, 1.76, C3, 4.80, paras, pad=0.0)

    line(sl, L, 6.58, R, 6.58, RULE, 1.0)
    tb(sl, L, 6.61, W, 0.26, [{"runs": [
        ("A 66-entry annotated bibliography, with a prior-art positioning table for each of the "
         "five mechanisms, is maintained alongside the implementation documentation.",
         8.6, False, MUTED)], "line": 1.0}], pad=0.0)


# =============================================================== build
def main():
    prs = Presentation(SRC)
    s = prs.slides
    slide1(s[0]); slide2(s[1]); slide3(s[2])
    slide4(s[3]); slide5(s[4]); slide6(s[5])

    lst = prs.slides._sldIdLst
    ids = list(lst)
    prs.part.drop_rel(ids[6].get(qn("r:id")))
    lst.remove(ids[6])

    prs.save(DST)
    print("wrote", DST, "-", len(prs.slides._sldIdLst), "slides")


if __name__ == "__main__":
    main()
