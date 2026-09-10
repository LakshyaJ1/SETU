# Delhi/NCR build verification

## Delivered build

`dist/android/SETU-ncr-6780e53.apk` is the historical testing build identified by
`build-evidence.json`. Its SHA-256 matched the APK installed for those checks on the
CPH2467 / Android 15 / arm64 phone. Existing user data was not cleared; the two
inspected original recordings still match their pre-update hashes. Subsequent
real usage exposed renderer-finalizer timeouts and low-memory exits; the checks
below did not establish sustained map stability. The replacement tiled renderer
is tracked separately in `../map-stability/README.md`.

- Debug app/test builds, 32 JVM tests and all 46 selected Python map/estimation
  tests pass. Lint has zero errors and 16 warnings. Signing and 16 KiB ZIP
  alignment checks pass.
- Final-APK instrumentation reports 33 tests: **32 passed, one assumption-skipped**
  captured-sensor replay. It checks the sensor/JNI path, native filter parity,
  trip storage, map import/download validation and the corrected native file URI.
  See `phone-regression-tests.log`; the skip is not counted as a successful replay.
- The complete NCR graph test passed on the preserved `SETU-ncr-routing-adcf28a.apk`,
  with the same map data and routing implementation. It calculates connected routes
  from Shahdara to MAIT, Noida, Ghaziabad and Meerut. That 33-test run took 340.137 s;
  see `ncr-routing-adcf28a.log`. The final APK corrects the native map file URI;
  the expensive graph test was not repeated after that URI-only application change.
- The final APK's roads/parks/water were visually observed with Location, Wi-Fi
  and mobile data off. Blue route styling was observed on the preceding routing
  build. Private screenshots and their APK-linked sidecars remain in
  `.shots/ncr-fixes/`, not in tracked public evidence.

The enlarged dataset has a **slow cold start**: prepare the map and route before
the presentation. First route preparation can take several minutes on this phone;
the graph stays in memory for subsequent routes, not across process restarts.
This is not a low-memory-device or fast-cold-start qualification.

## What the sensor test establishes

`gps-motion-alignment.json` is a controlled, **synthetic** acceleration/braking/
turning scenario through the real LiveEstimator/JNI pipeline, with a deliberately
disturbed compass. It aligns at 6.2 s, produces estimates during an eight-second
GPS omission, accepts no GPS during that omission and recovers afterwards.
Its approximately 0.32 m synthetic error is **not measured driving accuracy**.

Before the changes, replaying the user's latest inspected recording reproduced
the reported failure: 15,201 paired IMU samples but no initialized native pose;
335 sampled status messages reported magnetic interference. Raw sensor capture
was running. The alternate GPS-motion calibration and readiness diagnostics
address this failure mode, but have not been validated during the actual drive.

The complete Kirti Mandir-to-MAIT GPS-free journey remains **unverified**. The
ten-second, 150 m modeled-radius and 100 ms IMU-gap guards remain unchanged.
There is no absolute GPS-off cold start, route-driven fake position, surveyed
road accuracy result, or verified Kirti Mandir entrance in this evidence.

Device screenshot clocks are device-reported metadata, not a trusted wall clock.
Map-source timestamps are recorded separately in `source-build.json`.
