# Walking burst/tilt follow-up verification

Date: 2026-09-14. Device: OnePlus CPH2467 (Nord CE3 Lite).
Supersedes the [first walking build](../walking-fallback/README.md).

## Installed artifact

- Debug APK: `dist/android/SETU-walking-batch-fix.apk`, 212,472,278 bytes.
- SHA-256: `ee9304e300d7da6a5be51a3c63d35618c842ca08b61cf93c8d2dfffa2160afd9`.
- Installed `base.apk` has the same SHA-256. APK v2 signature and 16 KiB ZIP
  alignment checks pass. Installation retains app data.
- The earlier `SETU-walking-fallback.apk` remains unchanged with SHA-256
  `90ba2b978dbd575668173d5891a3e06464f36c84cc0c20bae10a15ecc18ddc4c`.

## Regressions

- 89 JVM tests pass, including 13 WalkingTracker tests. New cases cover batched
  detector events, normal pitch through vertical, a leading rotation callback,
  and implausible event floods without speed clamping.
- 12 Python collection/recording-analysis tests pass.
- Debug app/test assembly and lint pass; lint reports 25 warnings, no errors.
- 18 instrumented checks pass: 11 NativeEngine tests, synthetic walking callbacks,
  old Car-labelled walking replay, initialized batch replay, physical walking
  sensor registration/capture, an actual GPS-off stationary check, and two
  independent training-shadow replay checks. See `device-tests.log` (17) and
  `blackout-test.log` (1); tests with missing opt-in arguments are not counted.

## What the real recording establishes

The owner describes approximately 10 m between corridor endpoints, but did not
provide total traversals or counted physical steps. This is insufficient to
calibrate step length or score route accuracy. The configured step length remains
0.70 m; no value was fitted to this trial.

The 171.4-second recording contains 84 distinct platform step events, usually
delivered with timestamps clustered over about a millisecond in groups of two
to four every two seconds. The old per-event cadence gate accepted 17 and rejected
67. Its numeric walking speed stayed zero, and a later phone pitch invalidated
heading because a fixed forward axis became vertical.

`walking-batch-replay.json` reports the corrected initialized tracker replay:

- 84 events positioned, zero rejected; this is not proof of 84 actual footsteps.
- Peak speed 1.3988 m/s, final speed 0 m/s.
- 618 available outputs out of 710 GPS-off intervals. The remaining intervals
  are withheld, not counted as successful navigation.
- The replay supplies only the first recorded native bearing as initial heading,
  with a conservative 0.6 rad uncertainty, then processes the saved raw game
  rotation, paired IMU, GPS and step events. It does not fabricate footfall times.
- A cold full-estimator replay could not initialize from this file: alignment
  predates recording. The initialized replay validates the step/relative-turn
  regressions, **not** cold compass initialization or absolute heading accuracy.
  Production still requires its normal GPS/compass checks; training replay does
  not inject this diagnostic seed or use the recorded native path as truth.

The corrected delay before showing stop speed depends on batch timing: 1.5–4.5 s,
roughly three seconds with this phone's two-second batches. Burst reporting also
limits placement of individual steps around a sharp turn. Synthetic 100° turns
and pitch transitions pass; measured turning accuracy is still unverified.

## Physical device and data safety

Physical activity permission is now granted through Android's normal prompt.
The live Step detector diagnostic reads Active. Walking disables car-model
inference, including the formerly misleading zero-validity speed display.
The 30-second `walking-hardware.json` capture verifies raw sensors, step detector
registration and absence of car-model measurements. A capture without a native
pose cannot establish zero native speed or stationary position accuracy.

Initially GPS reported about 13 m accuracy and 0 km/h, the IMU ran near 200 Hz,
and compass interference correctly withheld heading instead of inventing a position.
After the owner moved the phone, a second 30-second hardware capture initialized
normally: 278 native poses all reported 0 m/s, with no detected steps or car-model
measurements. The Drive badge showed Tracking rather than Calibrating. This
validates still-phone speed behavior in these conditions, not walking accuracy.
Walking and its unchanged 0.70 m default are selected; no user recording was stopped.

An additional opt-in live test initializes normally, disables Android Location,
waits two seconds for pending GPS delivery to settle, then checks the current
Walking pose every 200 ms for 12 seconds. All 60 checks pass: timestamps advance,
speed remains 0 m/s, position and step count do not change, and no new GPS fixes
are accepted. Raw IMU recording continues. `walking-blackout.json` contains the
aggregate result; Location was restored and verified enabled afterward. This
proves a short **stationary** GPS-off interval, not GPS-free walking-route accuracy.

All 29 original `.setulog` files matched their pre-install SHA-256 values after
the regression run. Test-owned recordings were removed; user recordings were not.
Raw routes, exact coordinates and private source recordings are not checked in.
The evidence JSON contains only counts/status/aggregate speed, not locations.

These checks do not certify 90–95% accuracy, indefinite GPS-free navigation,
complex driving routes, or production readiness. See the
[investigation and measured-trial procedure](../../../23-walking-fallback-investigation.md).
