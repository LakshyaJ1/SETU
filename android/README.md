# SETU Navigator for Android

Native Kotlin / Jetpack Compose application. Open this `android/` directory in
Android Studio. The Python scientific reference remains at the repository root.

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
