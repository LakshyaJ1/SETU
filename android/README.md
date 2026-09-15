# SETU Navigator for Android

Native Kotlin / Jetpack Compose application. Open this `android/` directory in
Android Studio. The Python scientific reference remains at the repository root.

## Latest rigorous QA

See [phone QA and repeatable checks](../docs/28-rigorous-phone-qa.md) and the
[full PDF](../docs/verification/android/rigorous-qa/report.pdf) for six requested
outage durations, real Location-off sensor continuity, isolated regressions and
repeated app journeys. The earlier combined-test failures remain documented.
The application artifact is `../dist/android/SETU-qa-beta.apk`. Compact map
controls no longer overlap attribution, loading feedback stays above the sheet,
and the screen stays on during foreground recording. Model weights are unchanged.
Background sensor gaps remain unresolved; keep SETU visible for the demo.
GPS-free navigation accuracy is not approved.

## Curvier demo development build

Preceding development APK: `../dist/android/SETU-curvy-demo.apk`.
The presentation demo now includes alternating bends, corner braking and a stop.
Routes remain visible after screen recreation and theme changes; the phone test
checks rendered map features, not just status labels. See
[demo changes and the 6.8-minute CPU training experiment](../docs/27-demo-and-cpu-training.md).
The research checkpoint is not installed: held-out tests still show motion at rest.
This build passes 102 JVM tests, the demo visibility test and 25 physical-phone
regressions. The 90%-within-10-m GPS-free target remains unmet.
The combined 26-test run still fails its map-memory ceiling; see the follow-up
for exact results. This is a development build, not a bug-free release.

## Retained heading bootstrap improvement

Pooled GPS-motion heading initialization adds usable predictions in matched
replay without losing previously successful points or relaxing navigation guards.
See [the measured improvement and limitations](../docs/26-heading-bootstrap.md).
Normal training exports now allow 120 seconds of GPS warmup before 30-second
withheld intervals and describe the actual protocol. All original recordings remain
unchanged. [Verification and measured results](../docs/verification/android/road-stress/README.md)
include 675 synthetic trials and the three selected rides. The 90%-within-10-m
GPS-free target is not met. This is not the final navigation release.
The previous `../dist/android/SETU-heading-bootstrap.apk` and
`../dist/android/SETU-navigation-evaluation.apk` remain available.

## Scooter recording review

Previous test APK: `../dist/android/SETU-scooter-review.apk`.
Select **Settings → Activity → Two-wheeler** for scooter recordings. Good fresh
GPS remains the navigation source; unsupported car-only speed inference and car
mount/turn/vibration constraints are not applied to scooters. This does not make
sensor-only scooter navigation field-ready. The three selected rides still show
poor heading initialization; see [findings and next collection steps](../docs/24-scooter-data-review.md)
and [build verification](../docs/verification/android/scooter-review/README.md).

## Walking and stationary-speed fixes

Earlier test APK: `../dist/android/SETU-walking-batch-fix.apk`; its fixes are retained.
Select **Settings → Activity → Walking** for on-foot trials, allow **Physical
activity**, calibrate step length, and obtain GPS/heading alignment before testing
GPS loss. Walking does not run the car speed model. Keep a recording active during
the trial. No steps means no additional step displacement. Batched step reporting
is supported; stop speed can lag by 1.5–4.5 seconds (about three on the tested phone).
Ordinary phone pitch no longer erases initialized heading. Keep the phone pointed
along travel; magnetic interference still blocks unsafe compass initialization.
Walking field accuracy is not yet validated. See the
[investigation and test procedure](../docs/23-walking-fallback-investigation.md)
and [build verification](../docs/verification/android/walking-batches/README.md).
The earlier walking APK and its verification remain available separately.

## Recording-to-training pipeline

Record GPS and sensors together with the correct vehicle label and confirmed
fixed mount. Keep GPS enabled for reference data. After saving, use **Trips →
drive → Export training bundle** for raw data, a quality-marked 1 Hz comparison,
and independent GPS-withheld replay, prepared entirely on the phone.
See [collection, privacy, dataset conversion and fine-tuning](../docs/22-phone-training-pipeline.md).
The current model remains evaluation-only; this feature does not auto-train or
upload recordings. Keep SETU open while preparing an export.

The earlier collection build is retained at `../dist/android/SETU-training-pipeline.apk`.
[Verification and APK hash](../docs/verification/android/collection-pipeline/README.md)
include physical capture, leakage checks, regression tests and release limitations.

## Upstream review baseline

`../dist/android/SETU-reviewed-preview.apk` contains the reviewed teammate update
and fixes for map integrity, sensor/provider lifecycle, recording finalization,
model approval enforcement and delayed-GNSS constraint replay. The bundled local
speed model runs for evaluation, not approved navigation fusion. See
`../docs/21-upstream-review.md` for verification and open requirements.

## Presentation MVP

Delhi & NCR is included alongside Bengaluru Central. Select it in **Settings →
Offline area → Delhi & NCR → Use this map**. The expanded regional map includes
public local streets and a Shahdara-area-to-MAIT preview. Planned routes are blue;
dashed access links do not assert a drivable entrance. See `../docs/17-delhi-ncr-demo.md`
for coverage, calibration requirements and the portable offline pack. The crash-fix
build loads local vector tiles and corrects renderer lifecycle/readiness handling;
see `../docs/verification/android/map-stability/README.md` for measured checks.

Start with **Track my position** for a live recorded session, or
**Demo GPS loss & recovery** for the clearly labelled native-engine simulation.
The presentation sequence, APK locations and exact boundaries are documented in
`../docs/14-demo-mvp.md`. Native demo output is not a physical accuracy claim.

## Earlier reliability preview

The earlier build is `../dist/android/SETU-reliability-preview.apk`. It validates
and repairs offline tiles in persistent app storage, accelerates road snapping,
and publishes native estimates at 100 ms intervals when valid input is available.
See `../docs/verification/android/phone-reliability/README.md` for exact hashes,
device checks, failed tests and remaining acceptance work.

That build's connected-phone test froze background sensor capture despite a
recording service. Battery controls are in **Settings > Background recording**.
The reviewed update passes short foreground/background capture checks; consult
the current verification ledger for durations. This is not long-duration
screen-off qualification or proof of a complete GPS-free drive.

## Earlier routing preview

The earlier build is `../dist/android/SETU-routing-preview.apk` (202,214,737 bytes).
It includes the model-integration work below, replaces repeated NCR JSON graph
parsing with a verified, read-only compiled graph, and handles disconnected nearby
destination spurs without inventing road links. NCR drawing tiles are unchanged.
Verification: `../docs/verification/android/compiled-routing/README.md`.
This is a development preview with emulator tests and phone smoke checks, not a
field-validated navigation release. The stable MVP and earlier model preview are
retained separately.

## Model integration preview

The production work ledger is `../docs/18-production-delivery.md`. In **Settings →
Model integration**, save/check the supplied HTTPS endpoint, then explicitly enable
**Share during recordings** if you want live IMU evaluation. Sharing starts only
with a recording, stops when it ends, and is revoked when the endpoint changes.
GPS coordinates and saved trips are not uploaded.

The earlier model-only preview is `../dist/android/SETU-model-integration-preview.apk`.
Its evidence is in `../docs/verification/android/model-integration/README.md`;
the stable `SETU-demo-mvp.apk` is retained separately.

The current server identifies its CNN-GRU as experimental and returns validity
zero. Its speed/sigma are shown and logged for evaluation, not used for navigation.
Internet is required for this remote path; offline model export and calibrated
native fusion remain production requirements. Contract: `../docs/12-model-integration.md`.

## Build

Prerequisites: JDK 17 or newer, Android SDK Platform 37.0, NDK 28.2.13676358
and CMake 3.22.1. Set `ANDROID_HOME` to your SDK,
or set `sdk.dir` in an untracked `local.properties` file.

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`.
Minimum Android version is API 26. AI/ML weights are not required to build.
Compilation uses API 37.0; target SDK remains 36. The wrapper pins Gradle 9.4.1.
Native ABIs are arm64-v8a and x86_64. The first native configure downloads the
SHA-256-pinned Eigen 3.4.0 and GeographicLib 2.5 sources; AI/ML weights are not
downloaded. Small WMM2025 geophysical reference coefficients are packaged as
assets, with provenance beside them. This avoids silently extrapolating Android's
older geomagnetic reference beyond its documented interval.

If a synced workspace prevents Gradle from replacing generated native files,
leave those files untouched and use a local build directory:

```powershell
.\gradlew.bat :app:assembleDebug "-PsetuBuildDirectory=$env:LOCALAPPDATA\SETU\android-build"
```

Use the same property for subsequent build/test commands. APKs and reports then
live under that directory rather than `app/build/`.

```powershell
.\gradlew.bat :app:assembleDebugAndroidTest :app:connectedDebugAndroidTest :app:lintDebug
```

On-device UI tests exercise local search, routing, synthetic replay, diagnostics,
settings and theme switching. Separate device tests cover the road graph and
recording import, export, deletion and recovery. They save unaltered captures in
the app's external `files/verification/` directory. Tests do not validate road
safety, positioning accuracy or physical-device sensor rates.
The USB-phone rehearsal observes real GPS and approximately 200 Hz IMU. The newer
sensor-fallback build adds checked-compass initialization when numerical heading
accuracy is absent, timestamp-skew handling and saved sensor-estimated trajectories.
It still requires a starting fix and usable heading alignment. The NCR update adds
experimental GPS-motion alignment when the compass is disturbed; this requires
measured acceleration/braking and turns, not just waiting or constant-speed travel.
GPS-off prediction is bounded, not indefinite. Setup: `../docs/16-sensor-fallback.md`.
Current map/crash checks: `../docs/verification/android/map-stability/README.md`.
See `../docs/verification/android/delhi/README.md` for the Delhi build's APK-linked
phone checks, and `../docs/verification/android/demo-mvp/README.md` for the earlier
controlled native demo and physical GPS tracking evidence.
Native device tests compare the C++ filter against the Python reference fixture;
the exact contract and remaining streaming-engine work are in `../core/README.md`.

## Current work

This is an in-progress integrated application, not a verified release. The
authoritative completion and screenshot ledger is `../docs/11-android-delivery.md`.
GPS-only behavior and synthetic replay must not be mistaken for validated native
dead reckoning. Remaining integration and format gaps are recorded explicitly.

## Maps and team integration

The included Bengaluru region is generated from OpenStreetMap by
`python tools/build_android_region.py` from the repository root. It carries OpenStreetMap/ODbL attribution.
The offline graph currently lacks turn-restriction relations and is not a
production navigation routing engine.

Settings → Offline area manages local `.setumap` packages: import, direct
URL/checksum download, explicit selection and removal. The format, packager,
limits and publisher responsibilities are in `../docs/13-offline-map-packs.md`.
There is no hosted map catalogue yet. The packaged verification grid is
synthetic test data and must not be used for navigation.

The model handoff contract and local no-model server are documented in
`../docs/12-model-integration.md`. Product and visual rules live in this folder's
`PRODUCT.md` and `DESIGN.md`, rather than the desktop report's design system.
