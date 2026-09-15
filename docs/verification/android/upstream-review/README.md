# Reviewed Android update: verification ledger

## Build identity

- Source: `demo-mvp/position-tracking`, upstream `8d0c613` plus the review fixes.
- APK: `dist/android/SETU-reviewed-preview.apk`, 212,471,734 bytes.
- SHA-256: `1938f58e50b5711f8db022f924be777e46976754abbb4cdc0696b4f69deff002`.
- Debug signed; version `0.1.0` / code `1`. Identify this preview by its hash,
  not the shared development version number.
- CPH2467, Android API 35, arm64, connected through authorized USB debugging.
- APK v2 signature and 16 KiB ZIP-alignment checks pass. Installed `base.apk`
  has the same SHA-256 as the delivered artifact.
- Scope and remaining product requirements: `docs/21-upstream-review.md`.

## Automated checks

- Debug APK, instrumentation APK and Android lint build successfully using
  Android Studio's JBR. Lint reports 24 warnings and no errors.
- All 71 JVM tests pass, including new recorder failure/drain tests, model
  deployment/input-contract gates and provider lifecycle tests.
- Instrumentation covers native math/streaming/replay, actual packaged TFLite,
  GNSS metadata, model consent/HTTP contract, map integrity/routing/import,
  trip storage and UI workflows. Final device results are recorded below.
- Python reference suite: 213 collected; 210 pass, 2 skip and 1 fails. The
  pre-existing report test rejects the inline animation script. It is not an
  Android regression and remains explicitly unresolved.

### Phone results

The final regression suite completes with **62 passes, 2 explicit fixture skips
and no failures** (`delivery-device-suite.log`, 478.311 seconds). It covers real
NCR map rendering across six zoom/theme/disposal cycles, planned-route display,
UI settings/recording/replay/import, native estimation and local inference.
The skips are live GNSS/heading initialization and replay of an externally
supplied captured-sensor fixture (`cache/fallback-check.setulog`); neither is
counted as validation.

The additional offline run passes **all four checks**
(`delivery-car-hardware.log`, 150.527 seconds): actual route rendering with blue
color assertions, camera-follow and theme changes; packaged model inference and
unsupported-vehicle rejection; and one-minute foreground/background recordings.
Wi-Fi, mobile data and system location were disabled. The phone remained USB
connected with Battery saver enabled.

| Mode | Observed interval | Sensor events during interval | Local inferred windows | Maximum IMU timestamp gap |
| --- | --- | --- | --- | --- |
| Foreground | 60,001 ms | 32,948 | 57 | 5.006 ms |
| Background | 60,828 ms | 33,443 | 58 | 5.007 ms |

Both recordings save an end marker, have zero IMU pairing drops and retain
`navigationApplied=false` / validity zero for model outputs. These measurements
prove acquisition, local inference and recording continuity, **not absolute
position accuracy with GPS off**. They start without a live calibrated drive.

All 21 pre-existing raw recordings retain their original SHA-256 hashes, and
no test recordings remain. Wi-Fi, mobile data, location and the saved vehicle
selection were restored. No recording service is left running.

The phone's saved vehicle is Heavy vehicle, but the bundle supports only Car.
An initial stricter physical test therefore correctly obtained unavailable
results, not speed measurements. The corrected fixture temporarily selects Car
and restores the saved vehicle afterward; unsupported-vehicle rejection is
separately asserted. Do not describe Heavy vehicle as model-supported.

The baseline tile failure and early native failures are intentionally retained
in `baseline-tile-test.log` and `core-model-device.log`; the passing delivery run
supersedes them. `unsupported-vehicle-fixture.log` records the rejected Heavy
vehicle experiment, not a passing Car inference test. Full-suite memory samples
include accumulated test fixtures/mapped graphs; they are not a production peak
memory or battery qualification.

The earlier regression run reproduced one real settings navigation failure:
after scrolling the model page, Back was outside the viewport. The delivery
build keeps that header fixed and asserts that Back is visible before use.

`nativeGnssFixture` is an explicit prerequisite for the live GPS/heading UI
test. It is not enabled on this stationary indoor phone. The controlled native
GPS-loss, complex-motion, recovery and delayed-update tests are separate and
must not be presented as a physical drive.

## Reproduction

From the repository root in PowerShell:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
.\android\gradlew.bat -p android `
  "-PsetuBuildDirectory=$env:LOCALAPPDATA\SETU\android-review-build" `
  '-Dorg.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8' `
  --no-daemon --max-workers=2 `
  :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest :app:lintDebug

$adb = "$env:ANDROID_HOME\platform-tools\adb.exe"
& $adb install -r "$env:LOCALAPPDATA\SETU\android-review-build\outputs\apk\debug\app-debug.apk"
& $adb install -r "$env:LOCALAPPDATA\SETU\android-review-build\outputs\apk\androidTest\debug\app-debug-androidTest.apk"
& $adb shell am instrument -w -r `
  com.setu.navigator.test/androidx.test.runner.AndroidJUnitRunner
```

Select the intended device with `-s SERIAL` when more than one is attached.
Do not reinstall, force-stop or run instrumentation during a user's recording.
Keep the phone unlocked for UI checks. `LocationLifecycleTest` requires
`-e physicalHardware true`; it temporarily toggles system location and restores
the original state. Physical recording checks also require that opt-in.

For an explicit outage capture, first save radio settings, disable Wi-Fi,
mobile data and location, and run `PhysicalRecordingTest` with
`-e physicalHardware true -e requireLocationOff true`. Optional
`-e recordingDurationMs 60000` extends the sample to one minute. Always restore
the prior radio settings. No upload is enabled by these tests.

## Boundaries

- Rendering a blue route and acquiring real IMU samples do not prove correct
  vehicle positioning. No actual Shahdara-to-MAIT drive was performed here.
- The bundled model runs offline but is evaluation-only: deployment approval
  is false and uncertainty coverage misses G4. Logs must say
  `navigationApplied=false`, not pretend that queuing is native acceptance.
- The uncertainty/time cutoffs (400 m / 600 s) are not accuracy guarantees.
- Short background checks do not establish screen-off, thermal, battery or
  long-drive reliability across OEM devices. Earlier freezing evidence remains
  historical evidence, not something to erase after one successful run.
- Source changes and local VS Code settings remain uncommitted. Generated APKs
  are ignored by Git; build locally or copy the delivered artifact separately.
