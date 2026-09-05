"""Assemble the experiment report into one self-contained HTML file.

The page is an instrument readout, not a marketing surface. Its job is to let
someone decide whether the thesis of ``docs/03-approach.md`` 3.1 survived this
run, so the verdict leads, the falsification chart is the hero, and every number
carries the conditions that produced it -- ``docs/08-evaluation.md`` 8.1 is
explicit that no accuracy figure may be quoted without its tier, protocol,
baseline and percentile.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .charts import coverage_strip, error_vs_distance, trajectory
from .theme import CSS_VARIABLES, SERIES

__all__ = ["render_report", "write_report"]

# Split across lines only so the source stays readable; the URL is one string.
FONT_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=IBM+Plex+Mono:wght@400;500"
    "&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
)


def _esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _num(v: float, digits: int = 2, unit: str = "") -> str:
    if v is None or not np.isfinite(v):
        return '<span class="nil">—</span>'
    return f'<span class="num">{v:,.{digits}f}</span>{unit}'


STYLES = """
:root {
%(vars)s
  --measure: 68ch;
  --step: 4px;
  --radius: 10px;
  --font-sans: "IBM Plex Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  color-scheme: dark;
}

* { box-sizing: border-box; }

html { -webkit-text-size-adjust: 100%%; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.6;
  font-feature-settings: "kern" 1;
  /* A faint vertical gradient so the page reads as a lit panel, not a flat fill. */
  background-image: radial-gradient(120%% 70%% at 50%% 0%%, #16202B 0%%, var(--ground) 62%%);
  background-attachment: fixed;
}

/* Browser surfaces are part of the design, not the browser's business. */
::selection { background: rgba(40,168,118,0.32); color: #FFF; }
::-webkit-scrollbar { width: 12px; height: 12px; }
::-webkit-scrollbar-track { background: var(--ground); }
::-webkit-scrollbar-thumb {
  background: var(--rule-strong); border-radius: 8px;
  border: 3px solid var(--ground);
}
::-webkit-scrollbar-thumb:hover { background: #435566; }
* { scrollbar-color: var(--rule-strong) var(--ground); scrollbar-width: thin; }
:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
  border-radius: 4px;
}

.wrap { max-width: 1160px; margin: 0 auto; padding: 0 28px 96px; }

/* -- masthead ------------------------------------------------------------ */
.masthead {
  display: flex; flex-wrap: wrap; gap: 20px 40px;
  align-items: baseline; justify-content: space-between;
  padding: 40px 0 22px;
  border-bottom: 1px solid var(--rule);
}
.wordmark {
  font-size: 15px; font-weight: 600; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink);
  display: flex; align-items: center; gap: 11px; margin: 0;
}
.wordmark .expand {
  font-weight: 400; letter-spacing: 0.04em; text-transform: none;
  color: var(--ink-muted); font-size: 13px;
}
.provenance {
  display: flex; flex-wrap: wrap; gap: 6px 22px;
  font-family: var(--font-mono); font-size: 12px; color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}
.provenance b { color: var(--ink-secondary); font-weight: 500; }

/* -- verdict ------------------------------------------------------------- */
.verdict { padding: 56px 0 8px; }
.verdict .claim {
  font-size: clamp(30px, 5vw, 54px);
  line-height: 1.1; font-weight: 600; letter-spacing: -0.028em;
  margin: 0 0 22px; max-width: 22ch; text-wrap: balance;
}
.verdict .claim em { font-style: normal; color: var(--accent-bright); }
.verdict .claim.failed em { color: var(--bad); }
.verdict p {
  margin: 0; max-width: var(--measure);
  color: var(--ink-secondary); font-size: 17px;
}
.headline-figures {
  display: flex; flex-wrap: wrap; gap: 34px 52px; margin: 30px 0 0;
  padding: 22px 0 0; border-top: 1px solid var(--rule);
}
.figure { display: flex; flex-direction: column; gap: 3px; }
.figure .v {
  font-family: var(--font-mono); font-size: 28px; font-weight: 500;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; line-height: 1.1;
}
.figure .k { font-size: 12.5px; color: var(--ink-muted); }
.figure .v.good { color: var(--accent-bright); }

/* -- sections ------------------------------------------------------------ */
section { padding-top: 72px; }
h2 {
  font-size: 21px; font-weight: 600; letter-spacing: -0.015em;
  margin: 0 0 10px;
}
.lede { color: var(--ink-secondary); max-width: var(--measure); margin: 0 0 26px; }
.prose { max-width: var(--measure); color: var(--ink-secondary); }
.prose p { margin: 0 0 16px; }
.prose strong { color: var(--ink); font-weight: 600; }

/* A defined edge, not a floating elevation. An instrument panel is read by its
   bezel, and on a ground this dark a diffuse shadow contributes nothing but the
   generated-UI signature of pairing both. */
.panel {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 22px 20px 14px;
}
.chart { display: block; width: 100%%; height: auto; overflow: visible; }

/* Below the desktop width a dense technical chart scaled to fit is a chart
   nobody can read. The panel pans instead, so the type keeps its real size. */
.chart-scroll { overflow-x: auto; overscroll-behavior-x: contain; }
.chart-scroll > .chart { min-width: 720px; }
.chart-hint {
  display: none; margin: 10px 2px 0; font-size: 12px; color: var(--ink-muted);
  font-family: var(--font-mono);
}
@media (max-width: 780px) { .chart-hint { display: block; } }

/* SVG text roles */
.tick, .annot-muted, .row-label, .axis-title, .series-label, .row-value {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
}
.tick { font-size: 12px; fill: var(--ink-muted); }
.axis-title { font-size: 12px; fill: var(--ink-muted); }
.annot-muted { font-size: 12px; fill: var(--ink-muted); }
.annot-accent { font-size: 12px; fill: var(--accent); font-family: var(--font-mono); }
.series-label { font-size: 13px; font-weight: 500; }
.series-value { font-size: 12px; opacity: 0.8; }
.row-label { font-size: 12.5px; fill: var(--ink-secondary); }
.row-value { font-size: 12.5px; fill: var(--ink-muted); }

/* -- legend -------------------------------------------------------------- */
.legend {
  display: flex; flex-wrap: wrap; gap: 10px 26px;
  margin: 4px 0 20px; padding: 0; list-style: none;
}
.legend li { display: flex; align-items: baseline; gap: 10px; font-size: 13.5px; }
.legend .swatch {
  width: 26px; height: 0; flex: none; align-self: center;
  border-top-width: 3px; border-top-style: solid; border-radius: 2px;
}
.legend .name { color: var(--ink); font-weight: 500; }
.legend .detail { color: var(--ink-muted); font-size: 12.5px; }

/* -- table --------------------------------------------------------------- */
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%%; min-width: 640px; font-size: 14px; }
caption { text-align: left; color: var(--ink-muted); font-size: 13px; padding-bottom: 12px; }
th, td { text-align: right; padding: 11px 14px; border-bottom: 1px solid var(--rule); }
th:first-child, td:first-child { text-align: left; }
thead th {
  font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.07em;
  color: var(--ink-muted); font-weight: 600; border-bottom-color: var(--rule-strong);
}
tbody tr:last-child td { border-bottom: none; }
tbody tr.is-subject td { background: rgba(40,168,118,0.07); }
tbody tr.is-subject td:first-child { box-shadow: inset 2px 0 0 var(--accent); }
.num, td .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.nil { color: var(--ink-faint); }
.sys { display: flex; align-items: center; gap: 10px; }
.sys .dot { width: 9px; height: 9px; border-radius: 50%%; flex: none; }
.sys .nm { font-weight: 500; }

/* -- notes --------------------------------------------------------------- */
.notes { list-style: none; padding: 0; margin: 18px 0 0; display: grid; gap: 8px; }
.notes li {
  font-family: var(--font-mono); font-size: 12.5px; color: var(--ink-muted);
  display: flex; gap: 10px; align-items: flex-start;
}
.notes svg { flex: none; margin-top: 3px; }

.repro {
  margin-top: 22px; padding: 16px 18px;
  background: var(--panel); border: 1px solid var(--rule); border-radius: var(--radius);
  font-family: var(--font-mono); font-size: 13px; color: var(--ink-secondary);
  overflow-x: auto; white-space: pre-wrap; word-break: break-word;
}

footer {
  margin-top: 84px; padding-top: 22px; border-top: 1px solid var(--rule);
  color: var(--ink-muted); font-size: 13px;
  display: flex; flex-wrap: wrap; gap: 8px 28px; justify-content: space-between;
}

/* -- the one authored motion: the plot draws in ------------------------- */
@keyframes sweep { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.reveal-rect {
  transform-origin: left center;
  animation: sweep 1500ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
@media (prefers-reduced-motion: reduce) {
  .reveal-rect { animation: none; transform: scaleX(1); }
}

@media (max-width: 640px) {
  .wrap { padding: 0 18px 64px; }
  .verdict { padding-top: 38px; }
  section { padding-top: 52px; }
  .headline-figures { gap: 24px 32px; }
}
"""


def _icon(kind: str) -> str:
    """Small drawn marks. No emoji, no unicode glyphs standing in for icons."""
    paths = {
        "check": '<path d="M2 6.2 L5 9 L10 2.6" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        "dot": '<circle cx="6" cy="6" r="2.6" fill="currentColor"/>',
        "slash": '<path d="M2.5 9.5 L9.5 2.5" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round"/>',
    }
    return (
        f'<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
        f'{paths.get(kind, paths["dot"])}</svg>'
    )


def _legend(traces) -> str:
    items = []
    for tr in traces:
        spec = SERIES.get(tr.label)
        if not spec:
            continue
        style = f"border-top-color:{spec['color']};"
        if spec["dash"]:
            style += "border-top-style:dashed;"
        items.append(
            f'<li><span class="swatch" style="{style}"></span>'
            f'<span><span class="name">{_esc(spec["label"])}</span> '
            f'<span class="detail">{_esc(spec["detail"])}</span></span></li>'
        )
    return f'<ul class="legend">{"".join(items)}</ul>'


def _table(traces) -> str:
    rows = []
    for tr in sorted(traces, key=lambda t: -t.metrics.fpe_m):
        m = tr.metrics
        spec = SERIES.get(tr.label, SERIES["SETU"])
        subject = " class=\"is-subject\"" if tr.label == "SETU" else ""
        rows.append(
            f"<tr{subject}>"
            f'<td><span class="sys"><span class="dot" style="background:{spec["color"]}">'
            f'</span><span class="nm">{_esc(spec["label"])}</span></span></td>'
            f"<td>{_num(m.fpe_m, 2)}</td>"
            f"<td>{_num(m.drift_ratio * 100, 3)}</td>"
            f"<td>{_num(m.horizontal.p90, 2)}</td>"
            f"<td>{_num(m.along_track.p90, 2)}</td>"
            f"<td>{_num(m.cross_track.p90, 2)}</td>"
            f"<td>{_num(m.lane_keeping_rate * 100, 0)}</td>"
            f"<td>{m.n_anchors}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll"><table>'
        "<caption>Every figure is for the blackout window only. Percentiles, not means: "
        "the tail is what a driver experiences.</caption>"
        "<thead><tr><th>System</th><th>Final error (m)</th><th>Drift (%)</th>"
        "<th>Error p90 (m)</th><th>Along p90 (m)</th><th>Cross p90 (m)</th>"
        "<th>Lane-level (%)</th><th>Anchors</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_report(
    result,
    *,
    drive=None,
    title: str = "SETU · falsification run",
) -> str:
    """Render an :class:`~setu.eval.experiment.ExperimentResult` as HTML."""
    setu = next((t for t in result.traces if t.label == "SETU"), None)
    classical = next((t for t in result.traces if t.label == "B2_ins_nhc_zupt"), None)
    if setu is None:
        raise ValueError("report needs a SETU trace")

    m = setu.metrics
    score = result.scores.get("SETU", float("nan"))
    anchored = len(setu.anchor_distance_m) > 0
    failed = "FALSIFIED" in result.verdict

    # -- the headline claim, written from the data, not templated ---------
    if failed:
        claim = "The error did <em>not</em> reset at landmarks."
        lede = (
            "The central prediction of the approach is not supported by this run. "
            "Section 8.6 of the evaluation protocol is explicit about the response: "
            "fall back to the classical stack plus the speed heads."
        )
    elif anchored:
        claim = "Error <em>resets</em> at every landmark."
        lede = (
            f"Across {m.distance_m:,.0f} m with no satellites, "
            f"{len(setu.anchor_distance_m)} curvature registrations gave back "
            f"{score * 100:.0f}% of the error that accumulated between them. That is the "
            "structural claim: error bounded by anchor spacing, not by elapsed time."
        )
    else:
        claim = "No landmark was ever visible, and it <em>still</em> held."
        lede = (
            "Registration was unobservable on every window of this route, exactly as "
            "predicted for a straight road. The spectral odometer carried the whole "
            "blackout on its own, which is the case it was designed for."
        )

    ratio = (
        classical.metrics.fpe_m / max(m.fpe_m, 1e-9) if classical is not None else float("nan")
    )

    figures = [
        (f"{m.fpe_m:,.2f} m", "final position error", True),
        (f"{m.drift_ratio * 100:,.2f}%", "of distance travelled", True),
        (f"{m.distance_m:,.0f} m", f"blackout, {m.duration_s:.0f} s", False),
        (f"{m.cross_track.p90:,.2f} m", "cross-track p90", False),
    ]
    if np.isfinite(ratio):
        # One decimal. "{:,.0f}" rendered a 1.5x advantage as "2x", which
        # overstates the result on the most prominent line of the page.
        figures.insert(2, (f"{ratio:,.1f}×", "better than baseline B2", True))

    fig_html = "".join(
        f'<div class="figure"><span class="v{" good" if good else ""}">{_esc(v)}</span>'
        f'<span class="k">{_esc(k)}</span></div>'
        for v, k, good in figures
    )

    prov = [
        ("route", result.route),
        ("tier", result.tier),
        ("outage", f"{result.outage_s:.0f} s"),
        ("protocol", "8.1 · all GNSS withheld"),
        ("generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    prov_html = "".join(f"<span><b>{_esc(k)}</b> {_esc(v)}</span>" for k, v in prov)

    notes_html = "".join(
        f'<li><span style="color:var(--accent)">{_icon("dot")}</span>{_esc(n)}</li>'
        for n in setu.notes
    )

    # -- charts ------------------------------------------------------------
    hero = error_vs_distance(result.traces)

    traj_html = ""
    if len(setu.true_xy) > 2 and len(setu.est_xy) > 2:
        traj_html = f"""
  <section id="trajectory">
    <h2>Where it actually went</h2>
    <p class="lede">True path in grey, the estimate laid over it, registrations ringed.
      North is up and the aspect is not stretched to fill the box. A map that lies about its
      own geometry is worse than no map.</p>
    <div class="panel"><div class="chart-scroll">{trajectory(
        setu.true_xy, setu.est_xy, anchors_xy=setu.anchor_xy)}</div></div>
  </section>"""

    cover_html = ""
    if setu.channels:
        chans = [(name, ct, cv) for name, (ct, cv) in setu.channels.items()]
        cover_html = f"""
  <section id="coverage">
    <h2>Which channel could speak, and when</h2>
    <p class="lede">The design rule is that no two channels share a blind spot. The gaps
      are the content: where one falls silent another has to be carrying the estimate, and
      if they ever go quiet together the claim fails right here.</p>
    <div class="panel"><div class="chart-scroll">{coverage_strip(chans)}</div></div>
  </section>"""

    body = f"""
  <header class="masthead">
    <h1 class="wordmark">SETU
      <span class="expand">Seamless Egomotion Tracking under Unavailable-GNSS</span>
    </h1>
    <div class="provenance">{prov_html}</div>
  </header>

  <div class="verdict">
    <p class="claim{' failed' if failed else ''}">{claim}</p>
    <p>{_esc(lede)}</p>
    <div class="headline-figures">{fig_html}</div>
  </div>

  <section id="falsification">
    <h2>The experiment that could have killed it</h2>
    <p class="lede">Horizontal error against distance, with all satellites withheld:
      position, Doppler and satellite status alike. Withholding position alone is the
      flattering mistake; Doppler velocity is the single most useful GNSS product.</p>
    {_legend(result.traces)}
    <div class="panel"><div class="chart-scroll">{hero}</div>
      <p class="chart-hint">Drag the plot sideways to read the whole blackout.</p>
    </div>
    <ul class="notes">{notes_html}</ul>
  </section>

  <section id="reading">
    <h2>How to read it</h2>
    <div class="prose">
      <p>Every existing smartphone system answers <strong>“given acceleration, where am I
      after <em>t</em> seconds?”</strong>, a question whose answer degrades as
      <em>t</em>² no matter how good the network is. That is the steeply climbing
      line.</p>
      <p>SETU answers a different question: <strong>“how far along this road am
      I?”</strong> The state is an arc length on a one-dimensional road manifold, and it
      is observed by things whose error does not accumulate with time: the frequency of
      the axle harmonics in the vibration, lateral force divided by turn rate in a bend,
      and the shape of the road itself matched against the map.</p>
      <p>So the shape of the green line is the whole argument. Integration is still
      present, but it has been demoted from <em>the estimator</em> to
      <em>the interpolator</em> that carries between observations.</p>
    </div>
  </section>

  <section id="baselines">
    <h2>Against the baselines that matter</h2>
    <p class="lede">B2 is the real comparison: a well-tuned inertial stack with the
      non-holonomic constraint and zero-velocity updates. Any system that beats only pure
      inertial has proved nothing. This table is also the accessible view of the chart
      above.</p>
    <div class="panel">{_table(result.traces)}</div>
  </section>
  {cover_html}
  {traj_html}

  <section id="reproduce">
    <h2>Reproduce it</h2>
    <p class="lede">The run is deterministic: same seed, same bits.</p>
    <div class="repro">python -m setu.cli experiment --route {_esc(result.route)} \\
    --outage {result.outage_s:.0f} --open</div>
  </section>

  <footer>
    <span>SETU reference implementation · the Python twin of the estimation core</span>
    <span>Smart India Hackathon 2026 · SIH26168 · Sanskari&lt;CODERS&gt;</span>
  </footer>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{FONT_HREF}" rel="stylesheet">
<style>
{STYLES % {"vars": CSS_VARIABLES}}
</style>
</head>
<body data-palette="{",".join(s["color"] for s in SERIES.values())}">
<div class="wrap">
{body}
</div>
</body>
</html>
"""


def write_report(result, path: str | Path, *, drive=None, title: str | None = None) -> Path:
    """Render and write the report, returning the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        render_report(result, drive=drive, title=title or "SETU · falsification run"),
        encoding="utf-8",
    )
    return p
