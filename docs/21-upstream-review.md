# Android teammate-update review

## Reviewed source and scope

Reviewed on 2026-09-14. Fetched `origin` and fast-forwarded
`demo-mvp/position-tracking` from `29fee39` to `8d0c613` (71 changed files).
`origin/main` adds no different source content. Local VS Code settings were
backed up and preserved; no history was rewritten. Fixes remain uncommitted.

This review covers the shipping Android application, native estimation, local
model integration, maps, recording and their tests. It does **not** certify the
full research architecture or a GPS-free Shahdara-to-MAIT drive. The release
requirements in `18-production-delivery.md` remain requirements, not completed
features merely because the application builds.

## What the teammate actually implemented

| Area | Observed implementation | Acceptance boundary |
| --- | --- | --- |
| Native estimation | IMU propagation plus GNSS, mount estimation, NHC, ZUPT, SVO and CTS are wired into the C++ engine | Not just Python code anymore; synthetic benchmarks are not field accuracy evidence |
| Offline model | Packaged 206,848-byte TFLite speed model, timestamp resampling, local inference and live IMU windowing | Supports Car only. Bundle explicitly has `deployment_approved=false`; reported three-sigma coverage is about 96.33%, below 98% |
| Performance | Sparse A* workspace/heap, graph warm-up, pooled asynchronous recorder, off-main geometry construction and reduced auxiliary sensor rates | Cold graph preparation and real map I/O still cost seconds; sensor rate alone does not prove positioning latency |
| Offline maps | Delhi/NCR compiled roads and 11,159 vector tiles, Bengaluru, import and checksum verification | Existing geographic coverage is unchanged; not whole India or every administrative NCR district |
| UI | Consumer-facing navigation copy, diagnostics, recording/replay and settings | GPS loss must remain distinguishable from a valid inertial estimate; simulation must remain labelled |

## Defects corrected

| Priority | Defect | Fix and regression coverage |
| --- | --- | --- |
| High | In-process map-cache shortcuts trusted a surviving marker/length after deletion or corruption | Restore inventory/hash validation. The unmodified update failed `OfflineTilesTest` with a missing tile; fixed tests repair deleted, truncated and same-size-corrupt tiles and graph files |
| High | Unapproved local predictions received positive validity and could enter navigation | Require deployment approval and passing calibration; verify model/calibration hashes, input channel order/units/window and tensor types. Actual packaged inference returns validity zero |
| High | Delayed GPS replay erased intervening vehicle/speed constraint updates | Retain bounded per-frame observations with their original axes/sigma and replay them. The previously failing on-time/delayed-state equivalence test passes |
| High | Recorder shutdown could let a caller write/close while the worker was still draining, and hide write failure | Writer owns the end marker and close; timeout/failure is surfaced. Serialize producer shutdown and count invalid/dropped samples. Normal service stop drains off the UI thread |
| High | Delayed log serialization derived old trajectory entries from the newest live pose | Capture selected trajectory poses before queuing, not when the writer eventually drains |
| Medium | Launching with location disabled subscribed to no providers | Subscribe to available providers, cancel obsolete one-shot requests, reject callbacks after stop, and observe re-enable without restarting. Tested using the phone's real location switch |
| Medium | Interpreter instances survived session changes | Close providers on coroutine completion, after in-flight inference ends; unit coverage checks cancellation and closure |
| Medium | Future/duplicate speed inputs and optimistic `navigationApplied` logs | Reject future, repeated and stale timestamps; log whether native actually accepted the update. Restore synchronization on the native attitude entry point |
| Medium | Default local inference made the remote-provider UI effectively unreachable | Expose local evaluation selection; disable remote sharing while local is active. Switching evaluation source revokes sharing, requiring explicit consent again |

Tests also now distinguish a stopped hardware subscription from deliberate
mock injection. The live GNSS/heading integration test requires the explicit
`nativeGnssFixture` opt-in; a stationary USB-connected phone indoors is not that
fixture. This is a prerequisite, not a claimed pass.

## Delivery and verification

The debug-signed build is `dist/android/SETU-reviewed-preview.apk`.
Exact build identity, commands, phone results and limitations are recorded in
`verification/android/upstream-review/README.md`.

The delivery build passes 71 JVM tests and 62 phone regression checks, with two
explicit fixture skips. Four additional offline checks pass, including actual
blue-route rendering/following and 60-second foreground/background recordings
with local Car-model inference. All 21 original recordings are unchanged.

The wider Python test run still fails
`tests/test_eval_and_report.py::TestReport::test_renders_valid_standalone_html`:
the test forbids script tags while the existing report includes inline animation
JavaScript. This is outside the Android regression fixes and is not silently
reported as passing.

## Still not complete

- A validated GPS-free journey from Kirti Mandir, Road 60, Naveen Shahdara to
  MAIT. A stationary USB test cannot measure vehicle-path accuracy.
- Deployment-approved learned measurements, cross-rate/device parity, uncertainty
  coverage, latency gates and a truth-backed physical blackout evaluation.
- Full road-hypothesis/particle estimation and curvature-signature alignment.
  Planning a blue route is not measuring where the vehicle travelled.
- Reliable handling of low-speed/creep, mount changes, magnetic interference,
  long outages, and all required vehicles/device tiers.
- Production routing restrictions/access rules, broader map distribution, external
  IMU/edge delivery and the remaining production acceptance matrix.
- Long-duration background, screen-off and battery/thermal qualification. Short
  successful background tests do not resolve every OEM freezing scenario.

The native limits are now a **400 m modeled radius or 600 s without a fix**.
They are emergency withholding limits, not a promise of safe accuracy for that
distance or duration. Do not use this development build as your only navigation
aid or operate the phone while driving.
