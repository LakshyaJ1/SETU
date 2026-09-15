# Navigation release objective

## Full requested outcome

1. Complete the remaining Android/navigation implementation and demonstrate at
   least 90% GPS-free positioning accuracy, with a defined denominator and error
   threshold. Retain the requirements and gates in `08-evaluation.md` rather than
   substituting speed accuracy or successful-output-only accuracy.
2. Rigorously test Indian-road hazards, particularly potholes, alongside turns,
   stops, scooter lean, phone handling, clipping, gaps and GPS recovery. Separate
   synthetic stress tests, recorded-data replay and independent field validation.
3. Use Kaggle GPU training with valid splits, private data handling and model
   promotion gates; evaluate the actual Android/native/model combination.
4. After the application is complete, build the sibling `../setu-website/` site:
   explain SETU, invite beta testers and training-data contributors, match the
   Android visual identity with light mode by default, and serve the final
   verified APK. Do not publish an unvalidated preview as a final release.
5. Produce a visually polished, reproducible `metrics.pdf` comparing actual
   algorithms and documenting the evidence for the chosen solution. Missing or
   failed metrics remain visible; no simulated result is relabelled as field accuracy.

The current repository is `data/query/SETU`; the requested sibling is resolved
relative to this actual checkout, not by relocating or renaming the repository.
The website and PDF remain required deliverables, not optional follow-ups.

## Acceptance definition

The user confirmed the joint target: at least 90% of
GPS-free 10 Hz position outputs within 10 m of independent reference, counting
unavailable outputs as failures, across 10/30/60/120/180 s outages. This does not override the
existing short-distance, drift, coverage, recovery or regression gates.

For every result retain activity, phone/tier, mount, surface, duration, sample/run
counts, seed/split, reference quality and algorithm configuration. Report missing
outputs separately and in the joint success denominator. Confidence intervals
must respect correlation by drive/outage rather than treating adjacent 10 Hz
samples as independent trials. At least 120 s of GPS warmup is required for the
main comparison protocol. Short cold-start diagnostics remain separate.

## Current authoritative evidence

- Installed development APK: `dist/android/SETU-curvy-demo.apk`; its
  verified hash, 102 JVM tests, demo visibility test and 25 phone regressions are in
  `verification/android/road-stress/`. Earlier evaluation/scooter builds are preserved.
  Combined testing still fails the map process-memory ceiling; the failure is
  retained and the build is not represented as a clean final release.
- Three selected GPS-on scooter recordings have unconfirmed mounts. Local CPU
  training completed in 6.8 minutes using whole-ride-held-out folds, but the model
  still predicts motion at rest and is not approved or installed. No position
  accuracy follows from its speed metrics. Cold 30 s warmup replay is not adequate
  heading evidence and does not meet the requested accuracy target.
- The previous native benchmark had a clockwise-heading/gyro-sign inconsistency,
  scores displacement instead of travelled distance, uses too-short warmup and
  idealized speed-locked vibration. Its historical scores cannot justify release.
- Kaggle MCP is present but the quota call returned `Unauthenticated`; its
  authorization tool returned `Unexpected response type`. Reconnection is needed
  before GPU jobs can be submitted. No GPU job is running from this goal yet.

## Measured progress — 2026-09-15

- Corrected arm64 road-stress physics and missing-output scoring; ten executable
  self-checks pass. All 675 synthetic trials across 135 conditions completed.
  No algorithm passes the full requested target; raw IMU passes none of the 45
  benchmark condition subsets, constant velocity two, Car constraints six.
- Completed baseline 120-second-warmup, 10 Hz phone replay for all three selected
  rides and all five outage durations. Only two short moving fragments in the
  longest ride provide outputs; all other combinations are unavailable. See
  `verification/android/road-stress/ride-replay.json`, not the old cold-start
  summary, for this protocol. All 37 original logs remain byte-identical.
- Added pooled, bias-aware GPS-motion heading initialization. The matched phone
  replay now has estimates in 12/15 conditions, versus 2/15; all 186 previously
  successful points are preserved with unchanged errors. Long outages still
  contain mostly missing estimates. See `26-heading-bootstrap.md` and
  `verification/android/road-stress/pooled-comparison.json`. This is development
  evidence, not unseen field validation or an approved accuracy result.
- Normal training exports now use 120 s GPS warmup / 30 s withholding and record
  their actual protocol. Explicit short-warmup regression fixtures remain separate.
- Created and visually inspected the nine-page daylight `../metrics.pdf`, with
  full algorithm comparisons, archived speed-model evidence, real-ride results
  and the new CPU training experiment.
  It is a research report, not the eventual release certificate.
- Added a curvier native-engine demonstration and fixed map readiness/layout
  handling after Activity recreation. A rendered-feature phone test verifies
  visible reference and estimated routes through GPS loss/recovery and dark mode.
- A bank-/bias-aware turn-speed prototype passed isolated physics tests but
  regressed 23 of 45 Car stress conditions when fused. Its production integration
  was reverted; the negative experiment remains documented in
  `27-demo-and-cpu-training.md`. The shipping native kernel is unchanged.
- The final application accuracy, appropriate model promotion and website remain
  open. No navigation guard has been relaxed to inflate availability.

## Execution and completion audit

First repair and self-test the benchmark physics/scoring, add hazard scenarios,
and measure the shipping arm64 core without loosening navigation safety gates.
Then improve initialization, estimation and model behavior against held-out
protocols, including long-warmup replay of real recordings. Obtain suitable
independent data for training and road validation; preserve the original logs.
Run end-to-end phone tests and all release gates before promoting an APK.
Complete the matching website and the metrics PDF against those measured artifacts.

Completion requires evidence for every item above. Passing a simulator, disabling
a failing estimator, hiding unavailable intervals, creating a website, or writing
a report does not by itself complete this goal. The goal remains active until the
requested application accuracy and all delivery artifacts are actually verified.
