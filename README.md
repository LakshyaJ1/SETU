# SETU — AI/ML Intelligent Dead Reckoning for Seamless Navigation

**SIH problem statement:** *AI-ML based Intelligent Dead Reckoning system for seamless navigation.*
**Dataset:** IO-VNBD (Inertial and Odometry Vehicle Navigation Benchmark Dataset).

SETU = *Seamless Egomotion Tracking under Unavailable-GNSS*. Setu, "the bridge".

---

## The thesis in one paragraph

Every smartphone dead-reckoning system in the literature integrates acceleration twice, so its error
grows as t² or t³ and no network can repair that. SETU changes the question. Instead of *"where am I
after t seconds of acceleration?"* it asks *"how far along this road am I?"* — a scalar on a 1-D road
manifold, observed by three sources of information whose error **does not accumulate with time**:
the **axle-rotation frequency** hiding in the accelerometer's vibration spectrum, the **exact speed**
that lateral force and yaw rate jointly imply in every turn, and the **registration** of the
gyro-derived path shape against the road network's own geometry. Integration is demoted from being
the estimator to being the interpolator between fixes. The result is an error law bounded by
*anchor spacing* rather than *elapsed time*.

**Headline target:** ≈1 % of distance travelled in a 1 km tunnel, against a 10 % SIH gate and a
≈3.1 %/km published smartphone state of the art.

## Read in this order

| Doc | What it answers |
|---|---|
| [01 — Problem brief](docs/01-problem-brief.md) | What exactly is being asked, the error physics, REQ-IDs, acceptance gates, and the five IO-VNBD facts that shape everything |
| [02 — Landscape and gap](docs/02-landscape.md) | What already exists (academic + commercial), what it achieves numerically, and the four concrete gaps we attack |
| [03 — The approach](docs/03-approach.md) | **The core document.** SVO, CTS, CSA, PID, IAF, EFA — derivations, the calibration cascade, error budget, observability matrix |
| [04 — Technical architecture](docs/04-architecture.md) | Layers, module specs, interfaces, capability tiers, dataflow, threading, repo layout, C ABI |
| [05 — System design](docs/05-system-design.md) | Deployment, bundles, map pipeline, Android app, edge daemon, **seamless handover**, shadow calibration, schemas, failure modes |
| [06 — Tech stack](docs/06-tech-stack.md) | Every technology choice with its rejected alternative, plus dev/demo hardware and licences |
| [07 — Models and training](docs/07-models-training.md) | Model cards and budgets, feature contract, IO-VNBD pipeline, `R_eff` calibration, four training stages, export parity |
| [08 — Evaluation](docs/08-evaluation.md) | Outage protocol, metrics, CI gates, seven baselines, ten ablations, **the falsification experiment**, field trials, threats to validity |
| [09 — Roadmap](docs/09-roadmap.md) | Six phases with exit criteria, work breakdown, risk register, effort estimate |
| [10 — References](docs/10-references.md) | 66 references with links, plus a prior-art positioning table per mechanism |
| [IO-VNBD notes](IO-VNBD_NOTES.md) | Dataset schema, LFS retrieval, inventory, gotchas |

## The five mechanisms

| | Mechanism | Reads | Error behaviour | Blind spot | Covered by |
|---|---|---|---|---|---|
| **N1** | **SVO** — Spectral Virtual Odometer | axle/tyre harmonics in the accelerometer spectrogram | ∝ frequency-estimation error, **no accumulation** | needs ≥100 Hz IMU; weak below 4 m/s | CTS, ZUPT |
| **N2** | **CTS** — Coordinated-Turn Speedometer | `v = a_lat/Ω`; for two-wheelers `v = g·sin(φ)/ω_z` | ∝ sensor noise, **no accumulation** | straight roads | SVO |
| **N3** | **CSA** — Curvature-Signature Alignment | heading-vs-arclength registered to OSM, **scale-free** | **resets** error at each landmark | straight, featureless roads | SVO, EFA |
| **N4** | **PID** — Privileged-Information Distillation | IO-VNBD CAN wheel speeds as a training-only teacher | better labels ⇒ better student | — | — |
| **N5** | **IAF + EFA** — invariant filter with learned σ and Q, RB-PF over the road graph; magnetic/baro/radio anchors | multi-hypothesis posterior; field signatures | anchors **reset** error | anchors need a prior traverse | SVO, CTS |

The design rule: **no two mechanisms share a blind spot.** See the observability coverage matrix in
[03 §3.11](docs/03-approach.md).

## The one experiment that decides everything

Plot horizontal error against distance travelled during a simulated outage, with vertical markers at
curvature-landmark crossings. SETU predicts a **sawtooth** — error accumulating between landmarks and
dropping at each one, with no long-run growth. Every baseline predicts monotone growth. This runs on
IO-VNBD alone, in week 4, before any app is built. Protocol in
[08 §8.6](docs/08-evaluation.md). If the sawtooth does not appear, the thesis is falsified and the
fallback is the classical stack — which still passes every SIH gate.

## Honest disclosures, up front

- **IO-VNBD's smartphone stream is 10 Hz**, so SVO (N1) cannot be validated on it. IO-VNBD results
  are **Tier C** (SVO off); Tier A results require self-collected 400 Hz logs. No table mixes tiers
  without labels. [01 §1.5](docs/01-problem-brief.md), [04 §4.3](docs/04-architecture.md)
- **IO-VNBD has no two-wheelers and no Indian roads** — four cars in the UK, France and Nigeria.
  Two-wheeler support rests on the lean-form physics plus self-collected data.
  [07 §7.6](docs/07-models-training.md)
- **Ground truth in IO-VNBD is GPS, not RTK**, so sub-metre claims are not supportable on it.
- **CSA depends on OSM quality**, which is uneven in India; mitigations and an off-road fallback are
  specified. [05 §5.3](docs/05-system-design.md)
- Full list: [08 §8.9](docs/08-evaluation.md).

## Requirement traceability

| Requirement | Where it is met |
|---|---|
| REQ-F1 alignment & calibration | ACE — [03 §3.9](docs/03-approach.md) |
| REQ-F2 AI speed & vibration filter | SVO + CTS + `TimeDomainVelNet` + MSVR — [03 §3.3–3.4, §3.9](docs/03-approach.md) |
| REQ-F3 map matching & kinematic constraints | CSA + NHC + RB-PF — [03 §3.5, §3.7](docs/03-approach.md) |
| REQ-F4 AI GNSS+INS fusion | IAF with learned σ and Q — [03 §3.7](docs/03-approach.md) |
| REQ-F5 / P6 seamless handover | continuous trust ramp, no mode switch — [05 §5.6](docs/05-system-design.md) |
| REQ-F6 real-time UI | road-projected extrapolation, 300 ms damped blend — [05 §5.4](docs/05-system-design.md) |
| REQ-F7 edge engine, external IMU | one C++ core, two shells — [04 §4.1, §4.8](docs/04-architecture.md), [05 §5.5](docs/05-system-design.md) |
| REQ-F8 offline maps | PMTiles + graph + curvature LUT — [05 §5.2–5.3](docs/05-system-design.md) |
| REQ-F9 train in cloud, infer on device | four training stages, export/parity — [07](docs/07-models-training.md) |
| REQ-F10 screening submission | `ml/eval/screening_report.ipynb` — [07 §7.7](docs/07-models-training.md) |
| REQ-P1–P3 drift budgets | error budget — [03 §3.10](docs/03-approach.md); gates — [08 §8.3](docs/08-evaluation.md) |
| REQ-P4–P5 rates | 10 Hz phone / 200 Hz edge — [04 §4.5](docs/04-architecture.md), [05 §5.5](docs/05-system-design.md) |

## Status

Design complete; implementation not started. Next action per the roadmap: **Phase 0**, IO-VNBD
ingest plus the outage harness and a well-tuned B2 baseline — then the falsification plot.
