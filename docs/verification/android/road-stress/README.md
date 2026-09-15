# Navigation acceptance investigation — 2026-09-15

**Research evidence, not a navigation release.** The user-confirmed joint target
is at least 90% of expected GPS-free 10 Hz position updates within 10 m of an
independent reference across 10/30/60/120/180-second outages. Missing estimates
count as failures. Existing drift, short-distance, calibration, latency, recovery
and regression gates remain mandatory.

## Corrected synthetic comparison

The physical OnePlus CPH2467 completed **675 trials across 135 conditions**:
three algorithms, five outage durations, nine stress profiles and five paired
seeds. Every trial has 120 s GPS warmup and 200 Hz IMU, with no GPS or absolute
attitude assistance during the blackout. The full result, source hashes, paired
differences and complete-seed bootstrap intervals are in `comparison.json`;
`comparison.md` is the readable table. `../../../../metrics.pdf` is the vector,
selectable-text daylight dossier.

| Algorithm | Conditions passing the benchmark subset | Full target |
| --- | ---: | --- |
| Last-GPS constant velocity | 2 / 45 | Not met |
| Native unconstrained IMU | 0 / 45 | Not met |
| Native Car constraints | 6 / 45 | Not met; not applicable to scooter lean |

These condition counts are not positioning accuracy percentages. For example,
native IMU on the 10 s scooter-lean/pothole profile has **90.1% availability but
79.4% within 10 m**, with all five endpoints missing. Its 30 s joint success is
26.6%. Removing unavailable outputs would conceal the main failure.

The native uncalibrated 10 s / 150 m filter-radius guard is unchanged. At the
start of a withheld 1 Hz GPS window the last received fix can already be a second
old. A missing final error is null, never the previous valid position's error.
Car constraints remain a negative control on leaning profiles, not an approved
scooter estimator. No model was fused into these kernel comparisons.

### Benchmark corrections

- Correct clockwise navigation heading versus ENU gyro sign and arbitrary mount
  rotation; differentiate the simulated phone trajectory consistently.
- Measure travelled horizontal distance, not endpoint displacement.
- Add actual GPS noise, bias/random walk, roughness, smooth potholes, scooter
  lean, measured phone sensor clipping limits, 200 ms gaps and phone handling.
- Remove the ideal speed-locked vibration cue and blackout absolute attitude aid.
- Score every expected instant, including unavailable predictions; retain
  unavailable endpoints and conditional error labels.

The executable's self-test passes all ten checks. The profiles are controlled
synthetic failure mechanisms, not measured Indian-road/suspension statistics.
This does not test Android heading initialization, the learned model, maps or
GPS recovery. Five synthetic seeds do not establish real-world confidence.

## Real-ride replay

`ScooterCaptureReviewTest.measureLongWarmupBlackoutsWithoutChangingRecordings`
uses only the three explicitly selected rides. It gives each cycle 120 s of GPS
warmup, then withholds GPS for the requested duration and scores a fixed 10 Hz
timeline. Late GPS fixes cannot leak into the estimator. Reference interpolation
uses only quality-checked, bracketing GPS-provider observations; it never feeds
the estimator. These phone GPS comparisons are not independent survey truth.

An initial run of the new test exposed a reference-assembly bug: fused-provider
observations shared timestamps with GPS and overwrote them. That run was stopped
and invalidated, not reported as zero accuracy. The corrected v2 run filters to
the GPS provider and requires usable references. The existing training archive
and Python bundle converter already filtered correctly and were not affected.
Private incomplete/v1 output remains separate from accepted evidence.

The v2 phone test completed all 15 ride/duration combinations in 428.419 s.
`ride-replay.json` contains coordinate-free results and `ride-replay-tests.log`
records successful execution. The 9.007 km ride yielded 93/1,414 available
10-second-window outputs and 93/3,612 available 30-second-window outputs; all 93
in each group were within 10 m of quality-checked phone GPS. Conditional p90
separations were 5.19 m and 3.09 m. The other 13 combinations had no available
GPS-withheld estimates. Missing references are separately counted, not treated
as accurate predictions.

Unlike the earlier cold-start results, these two fragments were moving: about
250.1–259.3 s and 270.1–279.3 s into the recording, with preceding GPS speed
ranges 2.33–5.57 m/s and 2.12–6.52 m/s respectively. This demonstrates bounded
moving prediction, **not** complete-ride accuracy or the agreed 90% target.
Each duration uses its own fixed cycle grid, so its warmup windows differ.
GPS-motion alignment still often lacks sufficient consistent velocity changes,
while compass initialization requires stability and rejects interference.

Raw recordings and GPS-bearing archives stay under local AppData, outside this
repository/OneDrive. No private data was uploaded. The three rides remain
Two-wheeler / mount unconfirmed, diagnostic-only, without rewritten provenance.
All **37 original recordings** were SHA-256 checked again and are unchanged;
see `recording-preservation.json`.

## Pooled-heading improvement

The newer matched replay adds a bounded, bias-aware initializer for gentle
GPS-aided motion. `pooled-comparison.json` records all fifteen comparisons:
12/15 conditions now contain estimates, versus 2/15. Every previously available
and successful update remains; errors on those common points are unchanged.
This is not 12/15 accuracy: missing updates still dominate and newly available
estimates can exceed 10 m. The 10-second native guard is unchanged.

See `../../../26-heading-bootstrap.md` for the method, complete counts and
limitations. These three recordings informed development, not independent
validation. The unchanged native kernel's synthetic scores above do not evaluate
the Android pooled initializer.

Previous pooled-heading debug APK: `dist/android/SETU-heading-bootstrap.apk`, SHA-256
`6908ea59f2efe142d8fd61eb786e465a87bbd5fcfce3b41f3181c1cb488a6b64`.
`pooled-apk-verification.json` records signature, alignment and installed-hash
checks. SETU was reopened after testing; all 37 originals remain unchanged.

- 100 JVM tests and 41 focused Python tests pass; one ReportLab warning.
- All 15 matched phone replay cases complete in 371.789 s.
- 25 final-build phone regressions pass in 140.491 s.
- Android lint: zero errors, 25 warnings. Changed Python tools pass Ruff.
- That build's eight-page PDF included both the preserved baseline and new comparison;
  updated pages are visually inspected and every page's text bounds checked.

`pooled-replay-tests.log`, `pooled-device-regression-tests.log` and
`pooled-recording-preservation.json` retain the new verification evidence.

## Curvier demo and CPU training follow-up

Current installed development APK: `dist/android/SETU-curvy-demo.apk`, SHA-256
`aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`.
It adds alternating bends, corner braking and a stop to the native-engine demo,
and fixes invisible routes after Activity recreation. The reference remains
synthetic, not a real-drive accuracy result. Production native fusion and the
bundled Android model are unchanged from the pooled-heading build.

- 102 JVM tests pass; Android lint has zero errors and 25 warnings.
- The rendered-route demo test passes on the phone in 48.641 seconds.
- The separate 25-test phone regression suite passes in 138.392 seconds.
- The combined 26-test run has one failure: the map-disposal process-memory
  check measures 864,934 KiB against a 716,800 KiB ceiling. Its other 25 tests pass;
  the unchanged ceiling and failed log are retained. This is not a clean release.
- Signature, 16 KiB ZIP alignment and installed APK hash checks pass.
- All 49 focused Python tests and Ruff pass; one ReportLab deprecation warning.
- CPU training completed in 407.9 seconds: 40 epochs in each of three whole-ride
  held-out folds plus a separate all-rides checkpoint. `cpu-training.json` records
  the results and hashes; the checkpoint remains private and unapproved.
- The nine-page `metrics.pdf` adds held-out speed errors and standstill failures.
  These results do not establish the agreed GPS-free positioning target.

See `../../../27-demo-and-cpu-training.md` for limits and the rejected native
turn-speed experiment. `curvy-apk-verification.json` and the accompanying logs
retain final-build checks, including the earlier combined-test memory warning.

## Previous baseline APK and checks

`dist/android/SETU-navigation-evaluation.apk` is preserved from the previous test
round. Its installed hash was verified during that round. SHA-256:
`985a4ba2494850c82f928428abc7dd2a5b960ebce55bcc142725027f4324cea9`.
Size: 212,472,310 bytes. APK signature and 16 KiB ZIP alignment checks pass; the
installed APK hash matches. It is a debug/development build, not a production
release. `apk-verification.json` records these checks and the separately measured
long-warmup replay APK; changing the export default did not change the explicit
120-second replay configuration or the native estimator.

- **97 JVM tests pass.** Default warmup and late-GPS withholding are covered.
- **25 final-build phone regressions pass** in 139.903 s: collection/leakage,
  native engine, NCR maps/blue routes, walking, model consent/eligibility and
  Location off/on lifecycle. `device-regression-tests.log` preserves the results.
- **33 focused Python tests pass**, covering collection, recording analysis,
  benchmark validation and PDF generation; one ReportLab deprecation warning.
- Android assembly/lint succeeds: zero errors, 25 warnings. Changed Python tools
  pass Ruff. The older unrelated full-suite HTML-report failure is not fixed or
  represented as a passing full-repository run.
- The original seven-page PDF was rendered and visually inspected; selectable text remained
  within its printable area. It is intentionally local under the repository's
  existing presentation-deliverable ignore policy; the generator and evidence
  are included for reproduction.

## Reproduction

Build the arm64 benchmark using `core/test/README.md`, then push it and the WMM
coefficients to `/data/local/tmp/setu-road-stress/`. From the repository root:

```powershell
python -m tools.run_road_stress "$env:LOCALAPPDATA\SETU\road-stress-baseline-v1" `
  --adb "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" `
  --serial <authorized-device-serial> `
  --binary "$env:LOCALAPPDATA\SETU\road-stress-build\setu_dr_bench" --repeats 5
python -m tools.summarize_road_stress "$env:LOCALAPPDATA\SETU\road-stress-baseline-v1" `
  docs/verification/android/road-stress
python -m pip install -e ".[metrics]"
python -m tools.compare_phone_replays "$env:LOCALAPPDATA\SETU\long-warmup-v2" `
  "$env:LOCALAPPDATA\SETU\long-warmup-pooled" `
  docs/verification/android/road-stress/pooled-comparison.json
python -m tools.build_metrics_pdf --rides docs/verification/android/road-stress/ride-replay.json `
  --pooled-comparison docs/verification/android/road-stress/pooled-comparison.json `
  --cpu-training docs/verification/android/road-stress/cpu-training.json
```

The runner locks its output directory, checks device executable SHA-256, refuses
to duplicate a running benchmark or interrupt user recording, and pauses if
the phone is not powered, has less than 5% battery or exceeds 42°C. Completed
conditions resume only with identical experiment configuration and source hashes.
Execution failures and incomplete outputs are not accepted as benchmark failures.

The report includes the archived Car-only speed-model comparison from the real
bundle manifest. Its 96.33% three-sigma coverage misses the 98% gate and project
quantization parity remains failed. Kaggle MCP is unauthenticated; no new GPU job
has been submitted in this investigation. The website follows actual application
completion, not a premature final-APK claim.
