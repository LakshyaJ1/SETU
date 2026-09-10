# Reliability preview: APK and verification ledger

## Delivered build

- APK: `dist/android/SETU-reliability-preview.apk` (203,083,187 bytes).
- SHA-256: `84c120c458b573c68225acc1fd31ed9bde1fddb4d4f645e9b28a28e8b78b2947`.
- Debug-signed development preview; APK v2 signature and 16 KiB ZIP alignment pass.
- Installed on the CPH2467, API 35; the installed `base.apk` checksum matches.
- Branch: `demo-mvp/position-tracking`; base commit
  `ab84894a4ee5cf31716673bc4b70d26ee53e8ffe`, with uncommitted work preserved.
- **Not a completed production release or an accepted GPS-denied driving system.**

The newest UI adds background-recording setup guidance and an App info shortcut.
Its engine/map changes were also tested in the earlier phone-verified container
`SETU-phone-verified-preview.apk`, SHA-256
`5e7fe0fe3d87c556b404efd9de075e7dda6d4aede60a87d52397680b7e9076d8`.
An initial container used for the six phone UI checks had SHA-256
`3d964bae46b71022de2ffa8e21bfac8daa5766186df1b5cf3a20f3d85d17c088`;
its 220 runtime ZIP entries match the earlier phone-verified container byte for byte.
The latest APK is different: do not attribute the earlier complete phone runs to it.

## Checks and limitations

| Check | Outcome | Evidence |
| --- | --- | --- |
| Latest build, JVM tests | 49 passed | `final-build.log`, `jvm-test-results/` |
| Latest lint | 0 errors, 17 warnings | `lint-results-debug.xml` |
| Earlier phone core/map/native suite | 52 passed, 1 opt-in fixture skipped | `phone-regression-tests.log` |
| Earlier phone UI workflows | 6 passed | `phone-ui-tests.log` |
| Latest emulator UI workflows | 5 passed, 1 failed its pre-existing-map protection guard | `final-emulator-ui-tests.log` |
| Latest isolated emulator map renderer | Passed six NCR location/zoom/theme/disposal cycles | `final-emulator-map-test.log`, `final-emulator-map-rendering-stability.json` |
| Latest remaining emulator core checks | 15 passed, 1 opt-in physical fixture skipped | `final-emulator-remaining-tests.log`, `final-emulator-tile-integrity-metrics.json` |
| Latest phone core rerun | 36 passed, 1 UI-harness failure, 16 not completed | `final-phone-core-interrupted.log` |
| Latest phone background IMU test | Failed even with Battery saver off and background access allowed | `phone-background-no-saver-test.log`, `background-no-saver-state.json` |
| Separate 30-second physical foreground test | Passed with GPS, Wi-Fi and mobile data off | `final-phone-foreground-test.log`, `physical-foreground-recording-metrics.json`, `foreground-sampling-state.json` |
| Focused Python map tests | 39 passed, 2 skipped | `python-map-results.xml`, `python-map-tests.log` |
| Full Python suite | 210 passed, 1 failed, 2 skipped | `python-full-results.xml`, `python-full-suite.log` |

The emulator contained a pre-existing `verification-grid` map. The regional import
workflow refused to overwrite it; it was not removed to make the suite green.
The new background-help dialog did pass in the emulator settings workflow.

The final phone rerun encountered `No compose hierarchies found` after an external
foreground intervention while the phone was locked. It then stalled during the
tile test while the device slept. The operator stopped **that owned test process**
after checking that no recording service was active. Its runner reports
`Process crashed` following this deliberate force-stop; it is not evidence of a
spontaneous application crash. That interrupted run is not a clean acceptance run.
The secure lock screen was not bypassed. After the owner unlocked the phone, the
separate physical foreground recording test passed. Subsequent phone UI/map checks
are reported separately; the interrupted historical run remains in the ledger.
The latest APK's map renderer subsequently passed an isolated emulator rerun;
this does not retroactively turn the interrupted phone suite into a passing run.
The remaining tile-repair, demo, sensor-fallback and trip-store checks also passed
on the latest APK in the emulator, apart from the explicitly opt-in private fixture.

The full Python failure is
`tests/test_eval_and_report.py::TestReport::test_renders_valid_standalone_html`:
the scientific report contains a script where the unchanged test forbids one.
This unrelated report/test disagreement was not modified as part of Android work.
The changed Python files pass Ruff checks and formatting checks.

## Reproduced fixes

The old disposable tile cache contained only 2,057 files, including its completion
marker, instead of 11,159 tiles plus the marker. Street tile `13/5852/3415.pbf`
was absent, although its 94,470 bytes were present in the packaged archive. A live
renderer test failed twice on the phone before repair. See `baseline-device-tests.log`
and `baseline-isolated-map-test.log`.

Tiles now use persistent app files and a signed-APK-bound path/size/SHA-256 inventory.
Every source open verifies every required tile; deletion, truncation and same-length
corruption trigger staged local repair. The earlier full phone test verified all
three repairs, all 11,159 tiles, and a 1,539 ms verified warm open. The archive itself
is unchanged. See `tile-integrity-metrics.json` and `../../../20-phone-reliability.md`.

The road-block index uses 906,912 bytes and narrows start snapping from 7,255,057
directed edges to 727,808 candidates in the recorded NCR query. The earlier phone
run measured an 8,435 ms first route and 1,755 ms repeat route, with the same
25,796.29 m route distance. These are observations, not a latency guarantee.
`baseline-phone-graph-metrics.json` has an old hard-coded `emulator only` label,
but was collected over ADB from this phone; keep that metadata defect explicit.
`compiled-graph-metrics.json` records the later phone/device-specific scenario.
Neither benchmark is a measured production peak-memory budget.

The native publisher now uses 100 ms intervals, with pairing-drop counts logged.
Controlled tests cover GPS-supported, sensor-only and recovery cadence. They do
not validate physical positioning error or extend the ten-second/150-metre limit.

## Foreground hardware result

On the same installed APK, the unlocked CPH2467 recorded actual hardware sensors
for an uninterrupted 30,000 ms interval with location, Wi-Fi and mobile data off.
Battery saver remained on. The achieved accelerometer rate was 199.83 Hz, the last
published sample was 67.05 ms old, and the largest raw accelerometer/gyroscope
timestamp gap was 5.006 ms. The saved recording contained 6,215 accelerometer and
6,214 gyroscope records; native pairing reported 6,461 samples and zero drops.
Optional model sharing was off, no model measurements were recorded, and the
test-owned recording was saved and then removed by the test's cleanup.

This verifies foreground IMU acquisition and local recording without GPS or
internet. It does **not** validate a GPS-calibrated absolute trajectory, heading
accuracy, complex driving turns, or continuous GPS-denied navigation. The JSON's
legacy `backgroundMs`/`backgroundSensorEvents` fields describe the selected test
interval; its explicit `mode` is `foreground`. Radio settings were restored.

## Background capture is still blocked

The phone's OplusHansManager freezes SETU about eleven seconds after it leaves
the screen, including with a registered location foreground service and wake lock.
Both a test-driven recording and a recording started through the ordinary UI
reproduced this. Initially, a count-only test missed the interruption; the stronger
age/elapsed-time test catches it. Relevant device-only lines are in
`phone-background-freezer.log`; raw user recordings and unrelated phone logs are
not published here.

Enabling SETU's background allowance did not fix it. With Battery saver also off,
Wi-Fi/data off and location off, the nominal fifteen-second test took 144,918 ms
and the last sample was about 134 seconds old. This remains a failed test, not a
successful offline driving demonstration. A setup shortcut is guidance, not an
OEM-freezer workaround. Do not promise screen-off capture on this device.

The final hardware tests require explicit `-e physicalHardware true` authorization,
preserve pre-existing trips/settings and delete only their own completed recording.
For the foreground test, unlock the phone first, turn location/Wi-Fi/data off for
the interval, and restore their previous states afterward. With the test APK installed:

```powershell
adb -s f87ee0de shell am instrument -w -r -e physicalHardware true -e requireLocationOff true -e class com.setu.navigator.PhysicalRecordingTest#actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing com.setu.navigator.test/androidx.test.runner.AndroidJUnitRunner
```

Changing `Foreground` to `Background` selects the separate failing/background gate;
do not run both unintentionally, or call raw IMU continuity absolute-position accuracy.
Use a host timeout and record any manual foreground intervention: an OEM-frozen
instrumentation process cannot enforce its own timeout until it is resumed.

## Device and product state

All 20 original raw recording checksums still match. Two identified test-owned
extras were backed up privately and removed; no original raw recording was removed.
Wi-Fi is restored off, mobile data on, location on and Battery saver on. SETU's
app-specific background allowance remains enabled. No recording, debugger session
or debug-port forward is left running. See `device-final-state.json`.

The full requirements ledger remains `../../../18-production-delivery.md`.
Validated offline model weights/preprocessing, calibrated learned fusion, road-
constrained estimation and physical complex-drive truth measurements remain open.
The experimental provider's validity-zero results still do not control navigation.
Device/host clock timestamps in raw logs are collection metadata, not an asserted
release date.

## Source notes

Device behavior above is established by repository tests and local phone logs, not
inferred from generic Android documentation. General power-management context was
fetched with `webcmd web fetch --url https://developer.android.com/training/monitoring-device-state/doze-standby?hl=en`.
The first unqualified URL returned a redirect stub; the explicit-English fetch
succeeded. No browser fallback or plugin installation was needed. The web search
tool returned no usable results; it is not represented as supporting evidence.
