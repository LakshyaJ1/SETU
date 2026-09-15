# Scooter follow-up verification — 2026-09-15

Physical device: OnePlus CPH2467 / Nord CE3 Lite, authorized USB debugging.
The [investigation](../../../24-scooter-data-review.md) describes the fixes,
placement annotations, data exclusions and collection procedure.

## Artifact and preservation

The installed development build is `dist/android/SETU-scooter-review.apk`.
Size: **212,472,310 bytes**. SHA-256:
`dca73580e84cfd89efd7bdbd51cb169a4d3157d23f1946d2718b375cc0751539`.
`apk-verification.json` identifies its exact bytes/SHA-256, APK v2 signature and
16 KiB ZIP alignment verification, and match with the installed package.
This is a debug build, not a signed production release or an accuracy certification.
The previous `SETU-walking-batch-fix.apk` remains byte-identical.

All **37 original recordings** were SHA-256 checked after the investigation and
were unchanged. Only the selected 9.007, 2.387 and 3.423 km rides were copied and
exported for this dataset review. The approximately 28 m recording was excluded.
Test-owned short capture recordings are separate, removed from Trips by their tests,
and never added to the selected dataset. No user recording was deleted.

Raw logs, GPS-bearing ZIPs and live-location screenshots are kept privately under
`%LOCALAPPDATA%/SETU/scooter-investigation`, not in this repository/OneDrive tree.
Only coordinate-free summaries and test output belong in this directory.

## Controlled replay results

Protocol: independent native replay; cold reset every 60 s; GPS aiding for the
first 30 s, withholding for the next 30 s; no model-speed input or seeded heading.
The same three unchanged logs are replayed before and after the profile fixes.
Availability is reported across **all** withheld outputs, not only successful ones.

| Ride | Blackout outputs | Available before | Available after | Comparable after |
| --- | ---: | ---: | ---: | ---: |
| 9.007 km | 932 | 9 | 8 | 8 |
| 2.387 km | 308 | 0 | 0 | 0 |
| 3.423 km | 533 | 0 | 0 | 0 |

**Availability did not improve and remains inadequate.** The fixes remove
inappropriate Car assumptions and false handling resets; they do not solve
absolute heading initialization. Non-Car output cannot borrow the calibrated
Car's longer outage allowance. There is no measured successful moving-scooter
blackout in these replays.

The eight comparable outputs are one short interval approximately 150.94–157.95 s
into the 9.007 km recording. Their recorded GPS speed is **zero**, not riding speed.
Separation from interpolated phone GPS is 0.759–2.755 m; native speed drifts from
0.117 to 0.450 m/s. This is not evidence of accurate moving dead reckoning.
The summary's p50/p95 values (1.379/2.356 m) use lower order statistics on only
eight correlated samples and must not be presented as population accuracy.

Before the evaluation timing fix there were no comparisons because the epoch's
latest GPS fix differed from the prediction by about 0.66 s. The corrected scorer
interpolates only an explicitly separate evaluation reference from bracketing,
quality-checked GPS fixes, at most 1.5 s / 100 m apart. It never extrapolates or
feeds the withheld estimator. GPS itself has measurement error; this separation
is not RTK/survey error. Missing estimates remain failures, not zero-error samples.

## Training decision

All selected rides are complete with zero record drops and about 200 Hz IMU.
They retain **Two-wheeler / mount unconfirmed** metadata. The 9 km ride has an
imprecisely timed handling interval; the 2.387 km ride was in storage; unchanged
placement in the 3.423 km ride does not establish secure mounting. No provenance
was invented or rewritten.

The real bundle converter with explicit `vehicle="Two-wheeler"` rejects all three
for `mount_unconfirmed`. Same-phone/day samples cannot cross the required four
independent splits. These data support diagnosis, not a new deployable model.
No fine-tuning job ran, no weights changed, no private data was uploaded, and no
deployment gate was relaxed. See `training-eligibility.json`.

## Checks and boundaries

The final installed build passes **96 JVM tests and 23 phone checks** (237.061 s
for instrumentation). The focused Python collection/recording suite passes all
**17 tests**. Changed Python files pass Ruff. Assembly and Android lint complete
successfully. Re-exporting all three rides with this final APK produces the same
replay summary as the measured candidate; the last APK edit changes only home copy.

`tests.json` and `device-tests.log` record the completed test runs. Unit coverage
includes activity switching, unsupported-model activation, gyro-pulse consistency,
GPS preference, reference interpolation/gaps/antimeridian handling and leakage
gates. Phone checks exercise JNI bounds, actual activity reconfiguration, actual
capture/export, the three selected exports, walking regressions and explicit
training-export consent. NCR map checks render six location/zoom/theme/disposal
cycles and verify the blue planned route in follow mode and both themes.
Synthetic/replayed checks are not physical road truth.

The full Python run has **227 passes, two skips and one unrelated existing failure**:
`tests/test_eval_and_report.py:285` forbids `<script>`, but the upstream report
renderer includes its sweep script. Both `setu/report/` and that test are unchanged
from pulled commit `8d0c613`. It was not modified to conceal the failure.
The focused collection/recording tests pass; there is no claim that the whole
repository suite is green. Android lint has 25 warnings and no errors.

Remaining release gates include a usable scooter heading solution, true mounted
GPS-off moving trials, independent reference trajectories, multi-day/device/model
evaluation and thermal/battery/screen-off qualification. Recording fidelity and
passing software tests do not establish 90–95% positioning accuracy.
