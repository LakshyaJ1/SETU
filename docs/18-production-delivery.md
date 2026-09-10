# Production delivery ledger

## Objective and release rule

The approved objective is the complete SETU application, with Android first and
the supplied AI/ML endpoint integrated. This is not a redefinition of the product
as a demo or a network-only predictor. The normative requirements in
`01-problem-brief.md`, architecture in `04-architecture.md`, system design in
`05-system-design.md`, and roadmap definition of done remain the release scope.

The delivered increments connect the remote research provider to real IMU windows,
explicit consent, local evaluation logs and diagnostics, then add compiled NCR
graph loading and connected-road entrance fallback. They are concrete integration
work, **not completion of learned navigation or the full product**. The endpoint
responded to an 801-sample, four-second synthetic window with a speed result and
validity zero; a shorter window returned unavailable. No user's recording or GPS
coordinates were sent in those endpoint checks.

The phone-reliability increment in `20-phone-reliability.md` addresses missing
cached map tiles with persistent, inventory-verified preparation, adds a coarse
road-segment spatial index and changes native publication from 5 Hz to 10 Hz.
Its physical checks do not replace the field and full-estimator release gates.

## Requirement audit

| Requirement | Current evidence and remaining completion work |
| --- | --- |
| REQ-F1: automatic phone-to-vehicle alignment | Experimental compass/GPS-motion initialization exists. Full dash/cradle vehicle-frame calibration, handling detection and multi-device validation remain open. |
| REQ-F2: local learned speed/noise rejection | Remote research inference is connected for evaluation. Need deployable weights, exact input conditioning/axes, supported rates/vehicles, calibrated uncertainty, and offline runtime integration. |
| REQ-F3: road-constrained trajectory | Offline route planning exists; it is not map-matched estimation. Road hypotheses, kinematic constraints, curvature registration and ambiguous-grid handling remain open in the Android/native path. |
| REQ-F4: learned GNSS/INS fusion | Non-ML GNSS/IMU native fusion exists. Learned measurement ingestion with timestamp/innovation/validity gates, model calibration and end-to-end validation remain open. |
| REQ-F5: seamless GNSS handover | Bounded experimental fallback exists. Full outage support, latency and visible-jump gates are unproven; current safety limits are retained. |
| REQ-F6: continuous mobile navigation | Map/route/tracking/recording/replay flows exist. The connected CPH2467 freezes all-radios-off background capture despite its recording foreground service, including with Battery saver off; see `20-phone-reliability.md`. This and the remaining device/field acceptance gates are open. |
| REQ-F7: external IMU / edge engine | Portable native core exists. External-stream HAL, edge daemon, deployment, sustained 200 Hz and shared-model parity remain open. |
| REQ-F8: offline map database | Compiled NCR graphs, coarse segment indexing and inventory-verified persistent tiles exist; `19-compiled-road-graphs.md` and `20-phone-reliability.md` record the boundaries. Production routing hierarchy, turn restrictions/access rules, catalogue/publication and format/glyph coverage remain open. |
| REQ-F9: offline training / on-device inference | Python reference and training design exist. A remote URL is not an offline model bundle; export, quantization, manifests, rollback and Android runtime parity remain open. |
| REQ-F10: screening models / IO-VNBD plots | Requires reproducible dataset splits, model artifacts and evaluated predictions with no unavailable-GNSS leakage. Synthetic runs and endpoint availability do not satisfy this requirement. |
| REQ-P1/P2/P3: blackout drift/short/long errors | Physical and dataset-backed acceptance remains unproven. Simulator evidence must retain tier, baseline, outage protocol and percentile. |
| REQ-P4/P5: 10 Hz phone / 200 Hz edge | Measure output cadence, latency and dropped samples on release hardware; sensor acquisition rate alone is not output-rate proof. |
| REQ-P6: switch below 100 ms | Requires timed end-to-end mode-transition tests and field traces, not a UI badge change. |
| REQ-N1/N2: inference cost / model size | No bundled model yet. Remote request latency cannot satisfy the on-device 3 ms budget; test exported artifacts on reference hardware. |
| REQ-N3: battery | Long-drive screen-off battery/thermal device matrix pending. |
| REQ-N4: memory | Tiled maps address prior crashes, but do not prove the original 180 MB RSS target. Full routing-graph memory and device budgets require measurement; no emulator RAM limit is imposed by this work. |
| REQ-N5: cold readiness | Initial map readiness is not calibrated DR readiness. Measure the complete cold start and driving calibration against 20 seconds. |
| REQ-N6: metro map bundle size | Current map archives exist. Complete routing/curvature/anchor bundle must be measured against 250 MB after the production formats are implemented. |
| REQ-N7: privacy | Explicit endpoint-specific sharing consent, no GPS/trip uploads and cancellation are implemented for remote evaluation. Full log/container, anchor hashing, retention and distribution review remains open. |
| REQ-N8: deterministic replay | Raw storage/replay and kernel parity exist. Full native/model pipeline replay with identical output hashes remains open; a live remote service is not deterministic replay. |

## Acceptance evidence still required

- G-1/G-2/G-3: p90 drift, long-outage error and short-outage error across the required
  tiers/protocols, including the real dataset and physical truth.
- G-4: at least 98% three-sigma coverage; the current provider's uncalibrated sigma
  and zero validity explicitly do not satisfy this gate.
- G-5: tail-regression comparison against the last accepted release baseline.
- G-6: model tick below 3 ms on the reference phone with the actual local runtime.
- G-7: identical full-replay output hash from fixed sensor logs and model artifacts.
- G-8: p90 recovery below three seconds and maximum visible jump below two metres.
- T1–T8: tunnel, multi-level parking, urban canyon, forested highway, two-wheeler,
  truth-backed controlled blackout, three-phone spread and external-IMU edge trials.
- Release-commit CI must enforce all eight gates; existing partial/synthetic checks
  are not a replacement. Produce the falsification plot whatever the outcome.
- Reconcile JSONL `.setulog` with the specified versioned protobuf container and
  preserve existing recordings through migration. Add sensor/log drop accounting.
- Provide reproducible `make screening`, fixed-seed plots from raw data, the labelled
  field-trial report, one-page architecture summary and rehearsed six-minute demo.

## Implementation sequence

1. Complete and verify the current endpoint/consent/windowing/evaluation path.
2. Obtain the model bundle, preprocessing contract, uncertainty calibration and
   representative expected input/output fixtures from the model team. Integrate
   offline inference and timestamped gated measurements into the native estimator.
3. Complete alignment/mount logic, signal frontends, road-hypothesis estimation and
   replay parity. Do not replace these with animation along the planned route.
4. Productize offline graphs/maps, fix route correctness, harden storage, recording,
   permissions and lifecycle, and implement the portable edge/runtime delivery.
5. Implement all release gates, collect field evidence, measure resource budgets and
   publish the verified production build. Optional cloud/model/anchor publishing
   needs its own deployment access and validation; a public inference URL supplies
   neither weights nor operational credentials.

The goal remains active until these requirements have authoritative evidence.
