# DESIGN.md

Durable visual decisions for SETU's surfaces. Derived from the shipped report
generator in [`setu/report/`](setu/report/), not from intentions.

## World

**A dark instrument panel.** Chosen from the use scene, not from category habit:
an engineer reading experiment output, and a subject that is literally the
absence of signal. Traces read against a dark ground the way they do on any
telemetry instrument, and the darkness is earned by the topic rather than applied
as a default.

The register is *laboratory*, not *product marketing*. Data ink dominates;
chrome recedes. The page is a readout of a measurement, and its authority comes
from being precise rather than from being persuasive.

## Mode

**Operate.** The reader's success is a judgement — did the thesis hold on this
run — reached by scanning. Scanability, consistent alignment and legible numbers
outrank expression. Personality lives in the precision of the details.

## Surfaces and ink

| Token | Value | Role |
|---|---|---|
| `--ground` | `#0D1319` | page ground, a desaturated blue-black |
| `--panel` | `#141C25` | chart and table panels |
| `--panel-raised` | `#1A242F` | inset tracks inside a panel |
| `--rule` | `#26323F` | hairlines and table rules |
| `--rule-strong` | `#33424F` | header rules, scrollbar thumb |
| `--ink` | `#E8EEF4` | primary text |
| `--ink-secondary` | `#A9BAC9` | prose, ledes |
| `--ink-muted` | `#71889B` | labels, ticks, captions |
| `--ink-faint` | `#4A5C6D` | reference marks, truth path |
| `--focus` | `#4DA8E8` | focus ring |

Never pure black: it flattens depth and makes every shadow invisible. Ink is
tinted from the surface hue rather than gray.

## Series palette — validated, not chosen by eye

| Series | Colour | Meaning |
|---|---|---|
| SETU | `#28A876` | the system under test |
| B2 · INS + NHC + ZUPT | `#C08A1F` | the honest classical baseline |
| B1 · pure inertial | `#D6455F` | the divergence being avoided |
| B4 · speed, no map | `#4DA8E8` | isolates the map contribution |

Run through the dataviz validator against `#0D1319`:

```
lightness band   all inside L 0.48-0.67
chroma floor     all >= 0.1
CVD separation   worst adjacent dE 9.2 (protan), 13.5 (tritan)
normal vision    worst adjacent dE 17.5
contrast         all >= 3:1
```

Two rejected candidates, recorded so nobody re-derives them: a green/amber/**red**
set put amber and red too close in hue (normal-vision ΔE 12–14 — indistinguishable
even with full colour vision), and brighter versions of all three sat above the
lightness band, which would have given the series unequal visual weight. The red
is therefore pushed to crimson, away from the amber.

Hues are assigned in fixed order and never cycled. Identity is never carried by
colour alone: every multi-series chart has a legend, direct end-of-line labels,
and distinct dash patterns.

## Type

**IBM Plex Sans** for prose and UI, **IBM Plex Mono** for every measured
quantity. Plex was drawn for technical communication, its sans and mono share
skeletons, and its tabular figures are real. Loaded from Google Fonts with a
genuine fallback stack, because the product's own premise is that the network is
not guaranteed.

- Display claim: `clamp(30px, 5vw, 54px)`, weight 600, tracking `-0.028em`,
  `text-wrap: balance`, max 22ch.
- Body 16px/1.6, measure capped at 68ch.
- Every number carries `font-variant-numeric: tabular-nums` so columns of
  figures align and a changing value does not reflow its neighbours.

Monospace here is for data and measurement, never as a costume for "technical".

## Motion

**One authored moment**: the hero plot sweeps in left to right over 1500 ms on
`cubic-bezier(0.16, 1, 0.3, 1)`, an exponential ease-out from an already-visible
default. Nothing else animates — no per-section entrances. Fully disabled under
`prefers-reduced-motion`.

## Browser surfaces

Themed rather than left to the browser: text selection, the scrollbar track and
thumb (both WebKit and `scrollbar-color`), and the `:focus-visible` ring. These
are the cheapest signal that a page was built rather than assembled.

## Composition rules

- Structure is derived from the argument — verdict, evidence, reading,
  comparison, coverage, geometry, reproduction — not from a grid of equal cards.
- No kicker or eyebrow above any heading.
- Icons are drawn SVG at a consistent stroke; never emoji or unicode glyphs.
- Charts are hand-drawn inline SVG. No chart library and no CDN: the page must
  open from a local file with no network.
- A map is drawn at equal aspect with a scale bar. A map that lies about its own
  geometry is worse than no map.
- Charts spanning three decades use a log axis; a linear one would render every
  difference that matters as a flat line on the floor.
