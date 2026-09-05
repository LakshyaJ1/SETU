# 09 — Implementation Roadmap, Risks and Work Breakdown

## 9.1 Sequencing principle

**Prove the thesis before building the product.** The falsification experiment (§8.6) needs only
IO-VNBD, Python and a map extract. If the error law does not change, everything downstream should be
rescoped. So the plan front-loads the risky science and back-loads the certain engineering.

Second principle: **the classical stack is built first and kept forever.** B2 (INS+NHC+ZUPT) is both
the baseline and the fallback. It alone passes the SIH gates, so the project is never at risk of
having nothing to demonstrate.

## 9.2 Phases

### Phase 0 — Foundations (week 1)

| Deliverable | Detail |
|---|---|
| IO-VNBD ingest working | LFS fetch, encoding fix, `V-`/`S-` sync refinement by yaw-rate cross-correlation |
| `R_eff` calibration | least-squares per run, per tyre-pressure group (§7.3) |
| Outage harness | protocol of §8.1, 5 seeds, metric suite of §8.2 |
| Baselines B0, B1, B2 | in Python; B2 well tuned, not a straw man |
| Repo skeleton + CI | §4.7 layout, CMake builds, MLflow tracking |

**Exit criterion:** B2's drift-vs-duration curve reproduced and roughly consistent with the ≈3 %/km
published figure [R56]. If our B2 is much worse, our B2 is wrong, and every later comparison would
be dishonest.

### Phase 1 — Prove the mechanisms (weeks 2–4)

| Deliverable | Detail | Risk |
|---|---|---|
| **CTS** analytic speedometer | car form; validate against wheel odometry on roundabout-rich runs (`V-M`, `V-S2`) | low — it is algebra |
| **CSA** prototype | OSM extract for Coventry/Nuneaton/Rugby; curvature LUT; scale-free registration; report `sigma_s` | **high** — the novel piece |
| `TimeDomainVelNet` v1 | stage 1 + 2 training, PID distillation from wheel speeds | medium |
| **§8.6 falsification plot** | the go/no-go artefact | — |

**Exit criterion:** the sawtooth appears. Error resets at curvature landmarks. If it does not,
invoke the fallback in §9.4.

### Phase 2 — Estimator (weeks 5–7)

RI-EKF on `SE_2(3)` in Python first, cross-validated against a C++ twin; NHC/ZUPT/ZIHR; stochastic
cloning for delayed CSA measurements; RB-PF over the road graph; `AkitQNet` (stage 3); end-to-end
BPTT (stage 4). ACE (alignment) and MSVR (motion/mount) trained with the rotation augmentations.

**Exit criterion:** SETU (Tier C, IO-VNBD) beats B2 by ≥2× at p90 on 60 s outages, with 3σ coverage
≥98 %. **This is the screening submission** (§7.7), so it must be finished with slack.

### Phase 3 — Spectral odometer (weeks 6–9, parallel)

Depends only on self-collected data, so it runs alongside Phase 2. Build the collector app first
(400 Hz IMU + raw GNSS + OBD reference), collect 20+ hours across 3 vehicles and 3 phones, then
build the STFT/harmonic-sum/Viterbi ridge tracker and `FamilyNet`, and validate `v_svo` against OBD
speed. Target: **< 1 % speed error on Tier A**.

**Exit criterion:** the axle ridge is visibly trackable in real logs and `v_svo` beats
`TimeDomainVelNet` on straight sections. If the harmonic lines are too weak in practice, SVO is
dropped and Tier A collapses into Tier B — the system still meets every SIH gate, so this risk is
contained.

### Phase 4 — Productisation (weeks 8–12)

C++ core port and hardening; JNI layer; Android app (Navigate, Diagnostics, Drive log, Collect);
map pipeline productised; edge daemon; export/quantisation/parity harness; on-device shadow
calibration; EFA (magnetic/baro anchors) with the crowdsourced learning loop.

**Exit criterion:** 30 min live drive, phone only, GNSS denied for 3 separate stretches, marker never
freezes or jumps; all G-gates in §8.3 green.

### Phase 5 — Field trials and hardening (weeks 11–14)

Trials T1–T8 of §8.7; failure-mode drills from §5.10; device-farm battery/thermal runs; two-wheeler
data and the lean-form CTS; the final report with the §8.8 tables.

### Phase 6 — Finale readiness (week 15+)

Offline bundles pre-loaded; airplane-mode rehearsal; a rehearsed 6-minute demo script; a spare phone
with an identical bundle; a recorded fallback video of a successful tunnel run in case the venue has
no usable blackout site; a one-page results sheet with tiers and percentiles labelled.

## 9.3 Work breakdown by workstream

| WS | Owner role | Scope | Phases |
|---|---|---|---|
| WS-1 Data & Eval | ML engineer | ingest, sync, labels, augmentation, harness, baselines, plots | 0–5 |
| WS-2 Signal & Spectral | DSP engineer | conditioning, STFT, ridge tracking, notch, SVO, FamilyNet | 1–3 |
| WS-3 Estimation | robotics/estimation engineer | RI-EKF, RB-PF, NHC/ZUPT, cloning, learned `Q`, BPTT | 2–4 |
| WS-4 Maps & CSA | geospatial engineer | OSM pipeline, curvature LUT, landmark saliency, CSA, EFA | 1–4 |
| WS-5 Mobile | Android engineer | app, sensor HAL, JNI, UI, foreground service, collector | 3–5 |
| WS-6 Edge & Infra | systems engineer | C++ core, edge daemon, CI, packaging, determinism | 2–5 |

A six-person split maps cleanly onto a standard SIH team. WS-1 and WS-3 are the critical path;
WS-2 is the highest-variance, which is why it is parallel and non-blocking.

## 9.4 Risk register

| # | Risk | P | Impact | Mitigation | Fallback |
|---|---|---|---|---|---|
| R1 | CSA registration fails to converge / too ambiguous on real roads | M | High | landmark saliency scoring, top-k hypotheses in the RB-PF, honest `sigma_s` from the Hessian | classical HMM map matching on the DR output (B6); system still passes gates |
| R2 | Axle harmonics too weak on real phones/vehicles | M | Med | mount-quality gating, harmonic summation over many orders, `FamilyNet` σ | drop SVO; Tier A → Tier B; gates still met |
| R3 | IO-VNBD 10 Hz prevents Tier A validation | **Certain** | Med | capability tiers declared up front; self-collected 400 Hz data from week 2 | report Tier C on IO-VNBD, Tier A on own data, always labelled |
| R4 | No two-wheeler data in IO-VNBD | Certain | High (for Indian relevance) | lean-form physics residual makes the head data-efficient; collect T5 early | two-wheeler support declared as a validated extension rather than a benchmark claim |
| R5 | OSM quality poor at the demo site | M | High | survey the venue's map extract in week 1; off-road particle; optional Mappls adapter | pre-verify and, if needed, contribute the missing geometry to OSM |
| R6 | Android sensor rate throttled below 200 Hz on the demo device | M | Med | tier detection at runtime; `SensorDirectChannel`; verify on 3 devices | run the demo on the verified Tier A device; show Tier B on the others |
| R7 | 3 ms NN budget exceeded | L | Med | budgets are architectural; parity+latency gates in CI | reduce `AkitQNet` cadence to 1 Hz; shrink hidden sizes |
| R8 | Battery/thermal complaints on a long drive | M | Low | adaptive spectral duty cycle, thermal governor hook | reduce default tier to B |
| R9 | End-to-end BPTT unstable | M | Med | staged training; stages 1–3 alone already work; gradient clipping | ship stage-3 checkpoints |
| R10 | Overfitting to IO-VNBD's four cars | H | Med | driver/geography splits, held-out country, heavy augmentation, R-WhONet-style transfer [R19] | report held-out-country numbers as the headline, not the in-domain ones |
| R11 | Timeline compression (SIH reality) | H | High | Phase 2 exit *is* the screening deliverable; classical stack always demonstrable | descope EFA and the edge ROS 2 node first — neither is on a REQ gate |

R3 and R4 are marked *certain* deliberately: they are properties of the dataset, not risks to be
managed away, and the correct response is disclosure plus a data-collection plan.

## 9.5 Definition of done

- Every REQ-F and REQ-P in §1.3 mapped to a passing test or a demonstrated capability, in a table.
- All eight G-gates green in CI on the release commit.
- The §8.6 falsification plot published with the result, whichever way it came out.
- Field-trial report for T1–T8, with tiers and percentiles labelled per §8.8.
- Reproducible: `make screening` regenerates every submitted plot from the raw dataset with a fixed
  seed.
- One-page architecture summary and a 6-minute demo script rehearsed on the actual demo hardware.

## 9.6 Effort estimate

| Phase | Calendar | Person-weeks |
|---|---|---|
| 0 Foundations | 1 wk | 4 |
| 1 Mechanisms | 3 wk | 10 |
| 2 Estimator | 3 wk | 12 |
| 3 Spectral (parallel) | 4 wk | 8 |
| 4 Productisation | 5 wk | 22 |
| 5 Field trials | 4 wk | 12 |
| 6 Finale prep | 1 wk | 4 |
| **Total** | **~15 weeks** | **~72 person-weeks** |

Roughly a six-person team for a semester, with the screening deliverable landing at week 7.
