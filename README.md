# SETU — Seamless Egomotion Tracking under Unavailable-GNSS

Dead reckoning for the minutes when satellites are not available: tunnels,
multi-level car parks, urban canyons, dense tree cover, jamming.

**Smart India Hackathon 2026 · PS SIH26168 · Smart Vehicles · Sanskari&lt;CODERS&gt;**

> **Stop integrating time. Start registering space.**

Every published smartphone dead-reckoning system answers *"given acceleration,
where am I after t seconds?"* — a question whose answer degrades as t² however
good the network is. SETU answers *"how far along this road am I?"*, and observes
that with measurements whose error does not accumulate with time.

## What is in this repository

| Path | What it holds |
|---|---|
| [`docs/`](docs/) | The full design: problem brief, landscape, approach, architecture, system design, tech stack, models, evaluation protocol, roadmap, 66 references |
| [`setu/`](setu/) | The reference implementation of the estimation core |
| [`tests/`](tests/) | 169 tests, run against closed-form physics rather than snapshots |
| [`assets/`](assets/) | Deck figures and the presentation builders |
| [`PRODUCT.md`](PRODUCT.md) · [`DESIGN.md`](DESIGN.md) | Product truth and the visual system for the report surface |

This is the **Python twin** called for in
[`docs/06-tech-stack.md`](docs/06-tech-stack.md) §6.3. Its job is to make the
physics falsifiable and to cross-check the eventual C++ port — not to ship on a
phone.

## Quick start

```bash
pip install -e ".[dev]"

python -m setu.cli routes                       # routes, devices, capability tiers
python -m setu.cli outage --route curvy_a_road  # score one blackout
python -m setu.cli experiment --open            # the falsification experiment + report
```

The experiment writes a self-contained HTML report to `out/` and opens it.

## Results

Measured on the simulator, Tier A (200 Hz phone), a 60 s blackout with **all**
GNSS withheld — position, Doppler and satellite status alike.

| Route | Blackout | SETU final error | Drift | B2 baseline | Anchors |
|---|---|---|---|---|---|
| Curvy A-road | 887 m | **3.00 m** | 0.338% | 4.27 m | 13 |
| Straight motorway | 887 m | **5.44 m** | 0.613% | 319.87 m | 0 |
| Urban canyon | 657 m | 2.77 m | 0.422% | **0.75 m** | 13 |
| Roundabouts | 672 m | **3.20 m** | 0.476% | 5.84 m | 10 |
| Gentle motorway | 887 m | **19.57 m** | 2.205% | 659.83 m | 6 |

3-sigma coverage is 100% on every route, so the reported uncertainty is honest
as well as small (gate G-4 asks for 98%).

Two rows deserve comment. On the **straight motorway** registration is
impossible and only the spectral odometer survives, and SETU is 59x better than
the classical baseline: that is the case the whole method was designed for. On
the **urban canyon** B2 actually beats SETU. A grid of near-identical blocks is
self-similar in curvature, so registration occasionally locks onto the wrong
block, while a classical stack does well there because tight corners give it
frequent zero-velocity updates. That is the aliasing limitation described below,
showing up exactly where it should, and the fix is multi-hypothesis estimation
rather than tuning.

The SIH gate is 10% drift and a 100 m final error, so this sits 15–30× inside it.

**The falsification test passed.** 64% of the error accumulated between landmarks
is given back at them: the sawtooth predicted in
[`docs/08-evaluation.md`](docs/08-evaluation.md) §8.6 is present.

## How it works

Five mechanisms, each covering another's blind spot.

**SVO — spectral virtual odometer.** A rolling wheel is a rotating machine bolted
to the chassis, so the accelerometer already contains a wheel-speed sensor at
`f = v / 2πR_eff` and its harmonics. Every published system throws it away by
low-pass filtering at 5–20 Hz. Speed from a *frequency* has error set by the
spectral estimator, not by elapsed time. Measured here: **0.03–0.04%** median.

**CTS — coordinated-turn speedometer.** In a bend, `v = a_lat / Ω` outright: no
integration, no prior speed, no scale factor. So turns calibrate the odometer and
the odometer carries the straights. On a two-wheeler the chassis leans and the
lateral channel reads zero, so the lean-corrected form is required — omitting the
`cos φ` is a silent 4% scale error.

**CSA — curvature-signature alignment.** During a blackout there are no positions,
but there is *shape*, and heading is one integration rather than two. So the
problem is inverted: at what arc length does my heading profile best explain the
road's? Measured: 1.5 m median registration, and an honest refusal on straight
roads.

**EFA — environmental fingerprint anchors.** Magnetic and barometric signatures
per road edge, built as a by-product of ordinary driving.

**IAF — invariant adaptive fusion.** A right-invariant EKF on SE₂(3), so attitude
error propagates state-independently and the filter converges from the large
initial error an unknown phone mount actually produces.

## Design notes worth knowing

Each of these cost real debugging time and is recorded where it bites.

- A car rolls a degree or two on its suspension, and `g·sin(1.4°)` is a **12%
  speed error** in the lateral channel. CTS therefore sits downstream of the
  attitude estimate, never as a raw accelerometer ratio.
- The non-holonomic constraint is a statement about a *vehicle*. Applied in the
  phone frame it asserts something false: NHC acceptance went 2999/2999 →
  **0/5999** and the filter diverged past 7 km.
- `gaussian_filter1d(..., mode="nearest")` on a wide kernel replicates the
  boundary sample, so a "smooth random field" spikes at index 0. It started the
  simulated car at 126 km/h against a 60 km/h cruise.
- Interpolated curvature is not the derivative of interpolated heading at a
  corner. A truth built from both disagreed with itself.

## Honest limits

- IO-VNBD is not on disk, so results here are simulator results. The simulator's
  truth is exact, which a 1 Hz-GPS dataset cannot offer, but it is not real data.
- Tier A claims need real 400 Hz logs. A 10 Hz stream anti-alias filters the axle
  harmonics away, so SVO is genuinely *impossible* there, not merely degraded.
- A repeating urban grid is self-similar in curvature, so CSA can lock onto the
  wrong block. The fix is multi-hypothesis estimation (the RB-PF over the road
  graph), which this increment does not implement — there is a test asserting the
  failure is still present so it cannot vanish quietly.
- Not yet built: the Android app, the C++ core, the edge engine, the learned
  heads, and privileged-information distillation from IO-VNBD.

## Development

```bash
python -m pytest tests/ -q
ruff check setu tests
```

Every accuracy figure carries its tier, protocol, baseline and percentile —
[`docs/08-evaluation.md`](docs/08-evaluation.md) §8.1 forbids quoting one
without.
