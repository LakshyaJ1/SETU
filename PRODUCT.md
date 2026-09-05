# PRODUCT.md

> Written from the existing brief rather than from an interview. The `/goal`
> directive for this session was to implement without pausing to ask, which is
> the documented condition for inferring from the brief. Assumptions are marked
> **[assumed]** so they can be corrected cheaply.

## What this is

**SETU** — *Seamless Egomotion Tracking under Unavailable-GNSS*. A dead-reckoning
navigation system for the minutes when satellites are unavailable: tunnels,
multi-level car parks, urban canyons, dense tree cover, and deliberate jamming.

Built for **Smart India Hackathon 2026, problem statement SIH26168** (theme:
Smart Vehicles), by team **Sanskari&lt;CODERS&gt;**.

The full design lives in [`docs/`](docs/). This repository is the **reference
implementation** of the estimation core — the Python twin that
[`docs/06-tech-stack.md`](docs/06-tech-stack.md) §6.3 calls for, whose job is to
make the physics falsifiable and to cross-check the eventual C++ port.

## The one idea

> Stop integrating time. Start registering space.

Every published smartphone dead-reckoning system answers *"given acceleration,
where am I after t seconds?"* — a question whose answer degrades as t² however
good the network is. SETU answers *"how far along this road am I?"*, and observes
that quantity with measurements whose error does not accumulate with time.

## Who uses this repository

**Primary: the engineers building it.** They run experiments, compare an estimator
change against the previous green commit, and need to see immediately whether a
change helped the median while ruining the tail.

**Secondary: the SIH jury and reviewers.** They need to judge whether the central
claim is supported, and to see the conditions behind every number.

Both audiences want the same thing from the report surface: *did the thesis hold
on this run, and under what conditions?*

## What success looks like

The system is judged against gates in
[`docs/08-evaluation.md`](docs/08-evaluation.md) §8.3, of which the two that
matter most here are a p90 drift ratio below 10% of distance travelled, and a
p90 final position error below 100 m over a 1 km blackout at 60 km/h.

Measured on the simulator at Tier A, current standing is **0.32%–0.69% drift**,
which is 15–30× inside the gate.

## Non-negotiables

- **No number without its conditions.** §8.1 forbids quoting an accuracy figure
  without the tier, the outage protocol, the baseline and the percentile. Any
  surface that reports results carries all four.
- **Percentiles, never bare means.** The tail is what a driver experiences.
- **The honest baseline is B2**, a well-tuned inertial stack with the
  non-holonomic constraint and zero-velocity updates. Beating only pure inertial
  proves nothing.
- **Capability tiers are architectural, not caveats.** The spectral odometer is
  genuinely impossible below 50 Hz, and results must be labelled accordingly.
- **Failures are reported, not smoothed.** Where a method is blind it says so.

## Constraints that shape the work

- **Offline is the premise.** Tunnels have no connectivity; that is the entire
  point. Nothing in the runtime may require a network, and the report opens from
  a local file. **[assumed]** the report may load webfonts when online and
  degrade to a system stack when not.
- No IO-VNBD data is on disk, so the simulator with exact ground truth is the
  instrument everything is measured against.
- **[assumed]** The report is generated per experiment run, viewed on a desktop
  browser, and occasionally shown on a projector.

## Out of scope for this increment

The Android application, the C++ core, the edge engine, the cloud plane, learned
components (the heteroscedastic heads and adaptive process noise), and the
Rao-Blackwellised particle filter over the road graph. Their absence is recorded
where it bites — see the urban-grid aliasing test in `tests/test_estimation.py`.
