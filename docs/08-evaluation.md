# 08 — Evaluation Protocol

The rule for this project: **no accuracy number is quoted without the tier, the outage protocol, the
baseline and the percentile.** Most published smartphone dead-reckoning claims are unreproducible
because one of those four is missing.

## 8.1 GNSS-outage simulation protocol

```
For each test run:
  1. Warm-up: run with full GNSS for >= 120 s so biases, psi_bv and k_svo converge.
  2. Sample outage start epochs uniformly at random, minimum separation 3x the outage duration,
     excluding epochs in the dataset's GPS-loss index file, and excluding the first/last 60 s.
  3. During an outage window, withhold ALL GNSS: position AND Doppler AND satellite status.
     (Withholding position only is a common and flattering mistake -- Doppler velocity is the
      single most useful GNSS product, so leaving it in inflates results.)
  4. Continue for the full duration; record the estimate at 10 Hz.
  5. Ground truth: V- GPS at 10 Hz, converted to ENU about the outage start point.
  6. Metrics are computed over the outage window only.

Durations:  10, 30, 60, 120, 180 s          (matches WhONet's protocol [R18] for comparability)
Distances:  50, 200, 500, 1000 m            (matches the SIH benchmark statement)
Seeds:      5 fixed seeds; report mean and spread across seeds
```

Reporting against WhONet's duration set is deliberate: it is the strongest published IO-VNBD result
and the one a reviewer will look for.

## 8.2 Metrics

| Metric | Definition | Why |
|---|---|---|
| **FPE** | horizontal position error at outage end | what a missed exit actually depends on |
| **Drift ratio** | FPE ÷ distance travelled during the outage | the SIH gate (REQ-P1) |
| **ATE** | RMS position error over the whole outage window | penalises mid-window excursions |
| **Along-track / cross-track** | FPE decomposed in the road frame | separates the *speed* problem from the *heading* problem; essential for diagnosing which module to fix |
| **Heading error** | at outage end | drives the turn-instruction failure the statement describes |
| **Speed MAE / RMSE** | per-channel and fused, vs wheel odometry | isolates NVE quality from filter quality |
| **σ-coverage** | fraction of errors inside 1σ/2σ/3σ | honesty of the reported uncertainty |
| **NLL / CRPS** | proper scoring of the predictive distribution | the only way to compare estimators fairly when covariances differ |
| **Time-to-recover** | after GNSS returns, time until error < 5 m with no discontinuity > 2 m | REQ-P6 |
| **Lane-keeping rate** | fraction of the outage with cross-track error < 1.8 m | the practical definition of "lane-level" |

Every metric is reported as **p50 / p90 / p95 / max**, never as a bare mean. The tail is what a
driver experiences.

## 8.3 Acceptance gates (CI-enforced)

| Gate | Threshold | Enforcement |
|---|---|---|
| G-1 | p90 drift ratio < 10 % on every duration | blocks merge |
| G-2 | p90 FPE < 100 m at 1000 m / 60 km/h | blocks merge |
| G-3 | p90 FPE < 5 m at 50 m / < 60 s | blocks merge |
| G-4 | 3σ coverage ≥ 98 % | blocks merge |
| G-5 | no p90 regression > 5 % vs the last green commit | blocks merge |
| G-6 | per-tick NN latency < 3 ms on the mid-tier reference phone | blocks release |
| G-7 | replay determinism: identical output hash | blocks merge |
| G-8 | time-to-recover p90 < 3 s, max visible jump < 2 m | blocks release |

## 8.4 Baselines (all implemented in `ml/eval/baselines/`)

| ID | Baseline | Why it is included |
|---|---|---|
| B0 | Constant-velocity extrapolation along the routed polyline | what shipping navigation apps effectively do; the honest "do nothing clever" reference |
| B1 | Pure strapdown INS on the `S-` IMU | shows the t²/t³ divergence the whole design exists to avoid |
| B2 | INS + NHC + ZUPT + ZIHR, well tuned | **the real baseline.** Published equivalent: ≈3.1 %/km in a tunnel with a phone [R56]. Any team that beats only B0/B1 has proved nothing |
| B3 | Time-domain speed net + INS (CarSpeedNet-class [R7]) | the mainstream learned approach |
| B4 | 1-D CNN pseudo-odometer + NHC (OdoNet-class [R8]) | the strongest published untethered-speed-aiding approach |
| B5 | **WhONet with `V-` wheel speeds** [R18] | the privileged upper bound. Reporting how close a phone-only system gets to a CAN-bus system is the sharpest framing of the result |
| B6 | B2 + post-hoc HMM map matching [R33] | isolates the value of CSA versus ordinary map matching |
| **S** | SETU full | |

B2, B5 and B6 are the three that matter. B5 tells the jury the ceiling; B2 tells them the floor;
B6 tells them the map contribution is not just snapping.

## 8.5 Ablations

Each is a single Hydra config flag, so the whole matrix is one sweep:

| Ablation | Isolates | Prediction |
|---|---|---|
| `-CTS` | coordinated-turn speedometer | large degradation on roundabout/urban runs, none on motorway |
| `-CSA` | curvature-signature alignment | error grows monotonically with duration again (no flattening) |
| `-SVO` | spectral odometer | no effect at Tier C (already off); large effect at Tier A on straight sections |
| `-EFA` | field anchors | no effect on first traversal; large effect on repeat traversals |
| `-learned Q` (fixed `Q`) | A-KIT head | worse on rough roads and hard-brake scenarios |
| `-learned sigma` (fixed `R`) | heteroscedastic heads | worse tail, degraded σ-coverage |
| `-RBPF` (single EKF) | multi-hypothesis | catastrophic failures at interchanges; median barely changes — **the case for reporting p95, not p50** |
| `-PID` (train on GPS speed labels) | privileged distillation | quantifies the dataset-usage contribution |
| `-physics loss` | PiDR-style residuals | worse generalisation to the held-out country/vehicle split |
| `-invariant` (Euler EKF) | RI-EKF | slower cold start, worse under large initial mount error |

The `-RBPF` row deserves emphasis: single-hypothesis filters look fine on median metrics and fail
spectacularly in the specific situations (flyover vs road beneath) that produce the worst user
experience. This is the strongest argument for the tail-focused metric policy in §8.2.

## 8.6 The falsification experiment (the most important plot)

The central claim is a change in the **error law**: error should be bounded by *anchor spacing*, not
by *elapsed time*.

```
Experiment: for outages of 30..300 s on curvature-rich test runs, plot
      horizontal error   vs   distance travelled
   with vertical markers at every curvature-landmark crossing (from the map's landmark index)
   and at every magnetic-anchor match.

Prediction (SETU):    sawtooth -- error accumulates between landmarks, DROPS at each landmark,
                      no long-run growth.
Prediction (B2/B3/B4): monotone growth, roughly linear in distance (velocity-scale limited)
                      or super-linear (integration limited).
```

If the SETU curve does not visibly reset at landmarks, the thesis of §3.1 is falsified and the
project should fall back to the classical stack plus the speed heads (which would still pass the
SIH gates, but would not be novel). **Run this experiment in week 4, before building the app.**
It is cheap, it uses only IO-VNBD, and it is the single highest-information experiment available.

## 8.7 Field trials (beyond the dataset)

| Trial | Site | Duration | Measures |
|---|---|---|---|
| T1 Tunnel/underpass | a road tunnel or long underpass, both directions, 10 repeats | 2 days | REQ-P3; anchor-learning curve across repeats |
| T2 Multi-level parking | 4+ level structure, entry→top→exit | 1 day | REQ-P2, level accuracy, helix registration |
| T3 Urban canyon | dense high-rise district, peak traffic | 1 day | Doppler-only aiding, ZUPT-heavy regime, `T` ramp behaviour |
| T4 Forested highway | tree-canopy road | 1 day | partial-GNSS regime |
| T5 Two-wheeler | scooter + motorcycle, both mounts | 2 days | lean-form CTS, vibration robustness |
| T6 Simulated blackout | antenna disconnect / shielded enclosure on an open road | repeatable | controlled REQ-P1 with clean RTK truth throughout |
| T7 Device spread | 3 phones, same drive, simultaneous | 1 day | tier behaviour, cross-device consistency |
| T8 Edge + external IMU | ADIS16505 (and FOG if available) at 200 Hz | 1 day | REQ-P5, REQ-F7 |

T6 is the trial that produces defensible numbers: ground truth stays available (RTK) while the
navigation solution is denied GNSS, so error is measured, not inferred. Every claim in a final
report should trace to T6 or to the IO-VNBD protocol of §8.1.

## 8.8 Result-reporting template

Every table in every report uses this shape, so nothing is ambiguous:

```
System | Tier | Outage | n | drift p50 | drift p90 | FPE p90 (m) | along p90 | cross p90 | 3sigma cov
-------+------+--------+---+-----------+-----------+-------------+-----------+-----------+-----------
B2     | C    | 60 s   | . |           |           |             |           |           |
SETU   | C    | 60 s   | . |           |           |             |           |           |
SETU   | A    | 60 s   | . |           |           |             |           |           |
B5*    | C    | 60 s   | . |           |           |             |           |           |   (*uses CAN)
```

## 8.9 Known threats to validity (state these before a reviewer does)

1. **IO-VNBD has no two-wheelers and no Indian roads.** UK/France/Nigeria car data. Two-wheeler and
   Indian-road performance rests on self-collected data (§7.6, T5).
2. **IO-VNBD `S-` is 10 Hz**, so the dataset can neither validate nor refute SVO. Tier A claims must
   come from self-collected 400 Hz logs. Do not let a Tier A number and an IO-VNBD number appear in
   the same row without labels.
3. **Ground truth is GPS, not RTK,** in IO-VNBD — metre-level truth, so sub-metre claims are not
   supportable on this dataset. Use RTK in T6 for anything finer.
4. **CSA depends on OSM quality.** Results on well-mapped UK roads will flatter the method relative
   to poorly mapped Indian roads. Report the OSM-confidence distribution of the test set.
5. **Magnetic anchors need a prior traversal.** First-pass performance is the number to publish;
   repeat-pass performance is an additional, separately-labelled result.
6. **Simulated outages are optimistic** in one respect: a real tunnel entry involves a period of
   degraded-but-present GNSS that can poison the pre-outage state. T6 with a hard antenna
   disconnect is *also* optimistic for the same reason. The honest test is T1, a real tunnel.
