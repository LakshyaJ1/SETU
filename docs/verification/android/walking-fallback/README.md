# Walking/stationary-speed build verification

Date: 2026-09-14. Device: attached OnePlus CPH2467 (Nord CE3 Lite).

Historical build evidence. Physical activity permission was subsequently granted;
the real walking trial uncovered additional batching/tilt bugs. See the
[superseding build and checks](../walking-batches/README.md). Pending items and
phone state below describe this earlier build, not the current installation.

## Artifact

- Debug APK: `dist/android/SETU-walking-fallback.apk` (212,472,278 bytes).
- SHA-256: `90ba2b978dbd575668173d5891a3e06464f36c84cc0c20bae10a15ecc18ddc4c`.
- Reinstalled with app data retained. Installed `base.apk` hash matches the artifact.
- APK v2 signature verified; 16 KiB ZIP alignment check passed.
- Previous collection and reviewed-preview APKs remain available separately.

## Checks completed

- Gradle assembleDebug, assembleDebugAndroidTest, testDebugUnitTest and lintDebug
  succeed. **85 JVM tests pass**; lint has **25 warnings, no errors**.
- **12 Python tests pass**: collection pipeline and recording-analysis tests.
  Ruff check passes for the new analysis utility and its test.
- **16 instrumented checks pass on the phone**: 11 NativeEngine tests, two walking
  integration/replay checks, two training-shadow checks, and a foreground hardware
  recording with Location off. See `device-tests.log`.
- The 30-second hardware check recorded 6,207 accel and 6,207 gyro samples, including
  setup/stop margins; maximum raw IMU gap was 5.006302 ms. The live estimator reported
  6,221 paired samples and one pairing drop. It captured 28 local research-model
  windows, all with zero validity and none applied to navigation. This check used
  Car mode specifically to verify the existing recording pipeline, not walking accuracy.
- The walking integration fixture uses explicit synthetic platform callbacks.
  It proves steps, rather than a car model or raw acceleration integration, drive
  walking displacement, and that missing step permission withholds a usable pose.
- Settings → Activity → Walking and the 0.70 m default calibration field were
  inspected on the actual phone. No claim that 0.70 m is calibrated for this user.

## Private recording replay

The three owner-confirmed walking recordings were replayed read-only through the
corrected vehicle path because their original metadata says Car. No steps were
invented for these old files. The longest run now publishes no uncalibrated pose
older than **9.9448 s** since accepted GPS; it produces 319 available and 279 withheld
outputs. Maximum native speed in that replay is **2.0442 m/s**, versus the original
3.5745 m/s. This comparison is not a walking-accuracy score: much of the old output
is now correctly withheld, and no independent ground truth is available.

The other two recordings still cannot initialize a position. Their zero-validity
car-model peaks (12.4394 and 12.6128 m/s; longest run 12.9071 m/s) remain in the raw
files for diagnosis but are excluded from usable UI model speeds.

All 25 original `.setulog` files matched their pre-work SHA-256 hashes after the
final installation and hardware regression run. Tests delete only their own temporary trips;
private source logs and coordinate-bearing outputs are not included here.

## Still pending

The phone has not granted **Physical activity** permission. Android rejected an
ADB grant; the normal app permission prompt is used instead, not bypassed.
The dedicated `physicalWalkingProfileRecordsImuWithoutRunningCarModel` test was
attempted and stopped at its permission prerequisite. It is **not counted** among
the 16 passing checks. A real step-detector capture and measured out-and-back walk
remain pending that permission and user movement.

Walking is selected on the phone, with sensor fallback enabled. Location remains
off as originally configured; a fresh GPS/heading initialization is still needed
before live GPS-free walking. Do not interpret a withheld pose as measured zero
speed. No 90–95% accuracy target, complex driving route, background walking accuracy
or trained pedestrian model is certified by these tests.

See [investigation and next trial](../../../23-walking-fallback-investigation.md).
