# Sensor fallback verification

This directory separates the new sensor-fallback build from the earlier Delhi APK.
`build-evidence.json` identifies the installed APK and the checks actually run.
Device capture sidecars retain the phone's reported clock; they are not a trusted
wall-clock synchronization measurement.

## Passed checks

- Debug app/test assembly, 21 JVM tests, and lint with zero errors/16 warnings.
- All 27 Python estimation tests, including a rotation-in-place regression that
  failed before midpoint-attitude propagation; the 294-action native parity
  fixture is regenerated from, and checked against, the Python implementation.
- **23 focused instrumentation tests** on the authorized CPH2467 / Android 15 /
  arm64-v8a phone: `SensorFallbackTest`, `NativeEngineTest`, `NativeFilterTest`,
  `TripStoreTest` and `PositioningDemoTest`. See `phone-regression-tests.log`.
- The controlled turning scenario initializes with heading metadata `-1`, then
  omits GPS for eight seconds. Its maximum synthetic position error is about
  0.235 m. Removing gyroscope input changes the predicted path by about 1.85 m;
  removing dynamic acceleration changes it by about 3.56 m. This proves input
  dependence for this scenario, **not physical driving accuracy**. Details are
  in `sensor-fallback-metrics.json`.
- Replay of an existing physical-phone recording, with eight GPS observations
  deliberately omitted, processes 12,041 paired IMU samples and first aligns at
  about 2.60 seconds. It emits 284 native poses and 75 inertial-status samples.
  The replay also reaches the withheld state; it is not uninterrupted or unlimited
  tracking. See `captured-sensor-replay-metrics.json`. Private coordinates/raw
  recordings are not included in this directory.

## Real-phone check: not yet a successful live blackout

The phone initially has Location, Wi-Fi and mobile data off. The map still renders;
a cold-start recording collects motion samples but does not fabricate an absolute
position. `01-location-off-cold-start.png` shows that UI on the earlier candidate
APK, identified by its sidecar, not the final APK.

For the final build's live check, Location is temporarily enabled while both
internet connections remain off. The phone obtains GPS, but every magnetometer
sample in that session reports calibration code **0 (unreliable)**. Fusion does
not initialize; the UI directs the tester to calibrate away from metal. The check
therefore does **not** proceed to a live inertial-outage claim. Location is restored
to off and both network settings remain unchanged. The 25.535-second recording
contains 10 non-mock GPS observations and 10 separately stored GPS `track_pose`
entries, but **no native poses**. It ends cleanly and remains on the phone.

The existing calibrated recording above and the current unreliable compass are
different observations. A successful replay must not be substituted for a
successful live test. Calibration, a fresh starting fix, and another live GPS-off
rehearsal are still required; complex-path field accuracy is not established.
The private live capture is `.shots/fallback-review/02-live-initialization.png`.

## Found during verification

The first candidate passes the synthetic tests but fails the captured-data replay:
Android often delivers rotation events after slightly newer motion/magnetic samples.
The stability check wrongly treats that callback order as stale data. The corrected
check allows bounded cross-sensor skew and adds its angular effect to the model
prior, while genuinely future device-clock events remain rejected. The regression
now passes. `captured-sensors-before-skew-fix.log`,
`captured-sensor-replay-before-skew-fix.json` and `before-skew-fix-build.json` retain
the failed candidate evidence. `phone-regression-tests-first.log` belongs to that
candidate, not the final build.

All seven raw recordings present before this task retain their SHA-256 hashes.
New verification recordings are kept, not deleted. A separate 2.313-second recording
created during the work has an incomplete final sensor record and is recovered by
the existing recovery path; it remains saved, rather than being reported as a
cleanly ended capture. No app data is cleared. No mock Android provider is installed.
No recording is deliberately left running by verification.

## Remaining boundary

The engine still requires initialization and withholds estimates after ten seconds
without accepted GPS, excessive model uncertainty, or an IMU gap. The checked
compass uses an explicitly estimated 30-degree-plus prior, not a verified heading
error bound. GPS-denied walking/driving accuracy, long-session stability, battery
behavior and the full instrumentation stress suite are not validated by these
focused tests. Setup and policy details: `../../../16-sensor-fallback.md`.
