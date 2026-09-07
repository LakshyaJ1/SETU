# Android runtime evidence

## Scope and device

These are unaltered screenshots of the installed Android application, captured
using Android `UiAutomation.takeScreenshot` or `adb shell screencap`, not design
mockups. The test device is the local `SETU_API35` AOSP x86_64 emulator, API 35,
physically configured at 1080 x 2400 pixels and 420 dpi. The current automated set
uses a 720 x 1600 / 280 dpi emulator rendering override, retaining the same logical
viewport while reducing rendering load. Those PNGs are captured at that device
resolution, not resized afterwards. Earlier manual captures use 1080 x 2400;
the current map-management manual set (37–41) uses the same 720 x 1600 override.
Use installed-APK hashes in the capture sidecars to identify a build; displayed
clocks are test-environment timestamps.

Date note: verification spans September 6–7, 2026, with different local/UTC clock
representations. The September 7 recordings are emulator exercises, not claims
of real-world road drives. The current review date is September 7, 2026.

The repository's Android delivery remains **in progress**. This evidence covers
specific implemented workflows, not the whole product. No screenshot establishes
GNSS-denied accuracy, physical sensor performance, battery life or road safety.

## Screenshot index

| Capture | What to inspect |
|---|---|
| `verification/01-home.png` | Bundled street map, destination search, labelled navigation |
| `verification/02-destination-search.png` | Actual local place filtering |
| `verification/03-route-preview.png` | Route, origin, destination, estimated time and limitations |
| `verification/04-synthetic-replay.png` | Paused sample at 50%, source disclaimer and real map geometry |
| `verification/05-diagnostics.png` | Emulator sensor readings and explicit availability |
| `verification/06-record-ready.png` | Readiness and persistent Start recording action |
| `verification/07-trips.png` | Local trip library; contents depend on intentional capture tests |
| `verification/08-settings.png` | Native preferences and integration entry points |
| `verification/09-model-boundary.png` | Model configuration without fabricated inference |
| `verification/10-offline-area.png` | Active region, local map preview, source date and remaining routing limitations |
| `verification/11-home-dark.png` | Dark map and native controls |
| `verification/24-native-core-check.png` | Pinned diagnostics header and separate explicitly synthetic JNI kernel check |
| `verification/25-missing-gps-measurements.png` | Injected mock Location with optional fields absent: fresh observation, values explicitly not provided |
| `verification/26-measured-zero-gps.png` | Injected mock Location with measured zero speed/course/altitude; these remain different from missing values |
| `verification/27-stale-gps-position.png` | Stale injected location, visible last-test-fix label and nondirectional dot without a current accuracy area |
| `verification/28-outside-area-preview.png` | Injected GPS outside Bengaluru: MG Road preview remains usable, drive start is disabled, limitation is explained |
| `verification/29-live-native-diagnostics.png` | Actual emulator sensor callbacks driving native GPS/IMU estimation, delayed corrections and labelled model-derived radius; opt-in enabled |
| `verification/30-live-native-map.png` | The application selects a current native estimate for its map and labels GPS + IMU; not a physical drive |
| `verification/31-native-capture.png` | Actual foreground test recording; its saved file is checked for separate raw GPS, rotation-vector and experimental native_pose records |
| `verification/32-map-pack-installed.png` | Synthetic test pack installed alongside the included region, not selected automatically |
| `verification/33-map-pack-active.png` | Imported synthetic geometry rendered offline with its own metadata and limitations |
| `verification/34-map-pack-route.png` | Imported graph and named preview origin; no GPS contribution and drive start disabled |
| `verification/35-map-pack-removed.png` | Test-owned pack removed after switching back to Bengaluru; the scrolled map preview remains visible |
| `verification/36-map-pack-rejected.png` | A deliberately malformed archive is rejected with a recoverable message |
| `manual/37-map-download-form.png` | Explicit local debug URL and SHA-256, with catalogue and publisher-trust limitations |
| `manual/38-map-download-verified.png` | Actual checksum-verified download from the host loopback fixture server; no map auto-activation |
| `manual/39-map-document-picker.png` | Android's actual Downloads document picker, opened from SETU to select the synthetic pack |
| `manual/40-map-document-imported.png` | Successful import through the real content-provider selection, not just a test file URI |
| `manual/41-map-large-text.png` | URL, complete wrapping checksum and reachable download action at 200% system text; URL field scrolls horizontally |
| `manual/12-recording-active.png` | Actual emulator sensor capture; not a real road drive |
| `manual/13-recording-notification.png` | Visible foreground notification with Stop & save |
| `manual/14-recorded-trip.png` | Saved capture with GPS positions and sensor record count |
| `manual/15-export-picker.png` | Explicit user-selected export through Android's document picker |
| `manual/16-model-unavailable.png` | A successful check of the model-free loopback server |
| `manual/18-large-text-drive.png` | Drive screen at 200% system font size |
| `manual/19-large-text-record.png` | Start recording remains reachable at 200% font size |
| `manual/20-landscape-drive.png` | Native navigation rail and adjacent task pane in landscape |
| `manual/22-imported-trip.png` | Reimported 27,013-record capture retained after emulator restart, with its actual GPS path |
| `manual/23-recorded-replay.png` | Paused timestamped GPS replay; explicitly not live navigation |

Unlisted startup/loading images are investigative artifacts, not completion
evidence. The imported-trip captures were taken after an earlier emulator restart;
their sidecars identify that earlier APK, not the latest GPS-handling build.

## Repeatable checks

From `android/`, run:

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:connectedDebugAndroidTest :app:lintDebug
```

The device suite includes an end-to-end UI journey, route coverage and rejection,
recording round-trip export/import, malformed-input cleanup, interrupted-log
recovery, native/Python parity and invalid native inputs/closed handles. GPS checks
cover Android presence flags, valid zero values, optional uncertainty/altitude,
mock provenance, invalid/future/duplicate/delayed fixes, versioned/legacy decoding,
metadata persistence and the visible unavailable/stale/out-of-region states.
Screenshots are saved to the app's external `files/verification/`
directory. `tools/android-ui.ps1` provides small ADB helpers for manual checks;
do not run its UI Automator commands concurrently with instrumentation tests.

For the offline check, Wi-Fi and mobile data were disabled on the emulator while
the thirty-three-device-test suite ran. They were restored afterwards. The local model
server check is separate and requires network connectivity to `10.0.2.2:8765`.

The latest checked build has nine passing JVM tests, thirty-three passing device tests,
three passing Python packager tests, zero lint errors and 16 lint warnings. `validation/` contains the actual build,
test and lint output plus `build-evidence.json`. Each automated capture also has
a JSON sidecar containing the installed base-APK SHA-256. New manual captures
include the same build hash, font scale and rotation setting. Older manual
captures without sidecars belong to earlier development iterations.

Current installed APK SHA-256:
`8f9c49762b6278ef035342733ddd609b27f2a49c67346d8f584adaa7a31a4b26`.
All twenty-four automated sidecars match it. The complete device run passes in
286.787 seconds. JVM evidence is split between `validation/jvm-tests.xml` (four
geometry checks), `validation/pose-jvm-tests.xml` (one freshness check) and
`validation/imu-jvm-tests.xml` (four alignment/source-selection checks).
The four GPS-state screenshots (25–28) are controlled application-state tests, explicitly
labelled as test locations; they are not captures of physical satellite fixes.

The regional workflow (32–36) uses a synthetic Verification Grid, not additional
real-city coverage. It checks import without auto-activation, map/graph selection,
search, preview routing, replay mutation protection, removal and malformed-file
rejection. Separate isolated-store tests cover revision rejection, persisted
selection, corrupted-payload fallback, geometry/metadata validation, cooperative
cancellation and local HTTP integrity/redirect/truncation handling. The reproducible
fixture ZIP and its format are in `fixtures/` and `../../13-offline-map-packs.md`.
Manual download uses only the debug emulator bridge and the local fixture server;
it does not verify a public catalogue, publisher identity or a production TLS deployment.
The picker and import-result captures exercise Android's actual document provider.
The large-text check is limited to this form; it is not a full accessibility or
TalkBack certification. Font scale returns to 1.0, the synthetic pack is removed
and Bengaluru remains active after these checks. Existing recordings are retained.
Restoring font scale caused the manual automation to lose its UI root; SETU was
no longer foregrounded and was relaunched to finish cleanup. No matching crash
was established from the captured exit information. Seamless configuration-change
restoration remains unverified, rather than being inferred from the 200% screenshot.

Visual inspection caught a uniform blank map preview after returning from a
scrolled region list. The map now uses texture-backed composition. The same
interior rectangle changes from one uniform colour to 1,782 colours and visibly
contains the Bengaluru streets in the unaltered post-removal capture. See
`validation/map-preview-regression.json` and the preserved before image in
`investigation/`. An interrupted full run is retained separately; a fresh isolated
journey check and then the entire 33-test suite pass. A thread trace taken during
the slower full run shows normal application idling and ongoing screenshot capture,
not evidence of a renderer deadlock. These checks do not establish frame rate,
battery life or freedom from all graphics/device issues.

The live native workflow (29–31) instead consumes actual Android sensor and GPS
callbacks from this emulator after `adb emu geo fix 77.5968 12.9810 920`. It checks
paired samples, accepted fixes and current output before enabling native map
selection. It then records while foregrounded and inspects the saved JSON Lines
for raw GPS, rotation-vector and at least five separately named experimental
native estimates with positive radii and increasing timestamps. Its uniquely
created test recording is removed afterwards; existing recordings are preserved.
The same workflow selects mph and verifies that native speed respects the unit
preference. Settings are restored afterwards. The capture helper waits for a
fresh Compose frame after its map-settling interval before taking the screenshot.
This does not repeat the foreground-service/background notification exercise or
prove physical sensing/accuracy. The original retained import still matches its
recorded SHA-256. Native counter fields in capture sidecars are sampled after the
screenshot and can differ from its displayed frame; use them as runtime context,
not pixel-exact counter assertions.

The native parity fixture exercises two cases, 294 actions, its original eight measurement
families and all 279 snapshot values at checkpoints. The x86_64 library is runtime
tested; arm64-v8a is compiled, not physically validated. A separate engine test
covers the added horizontal-velocity kernel update. Seven engine tests exercise
bounded delayed corrections, initialization, missing altitude, pending fixes,
outliers, gaps, outage withholding, mock-provenance retention and lifetime. Twenty
applicable low-altitude examples from NOAA's WMM2025 test file match within the
published two-decimal declination precision. `validation/native-stream-targeted.log`
is an earlier focused run; the current full device log includes the final tests.
The visible kernel button remains deliberately synthetic and separate from the
live stream. None of these checks establishes calibrated blackout accuracy.

Windows denied replacing a generated native-library directory in the synced
workspace. The successful build leaves those files untouched and uses
`-PsetuBuildDirectory=$env:LOCALAPPDATA\SETU\android-build`; see `android/README.md`.

## Measured capture, not a benchmark

The intentionally named `Emulator capture test` recorded 27,013 records and 60 GPS
positions over 67,228 ms. Ten `adb emu geo fix` inputs changed longitude along a
short synthetic path; the emulator's sensors generated the remaining readings.
The original `.setulog` and the document-picker export both had SHA-256
`26dd3beed4777818de88939d15d50a90aeb7723e583dd12318a13a58ca5441ab`.
That comparison establishes an exact export for this capture, not estimator
accuracy. The foreground-service stop action was exercised from the notification.
The original test capture was then deleted through its confirmation dialog and
the exported file reimported through Android's document picker. It received a new
local ID and retained the same raw-file SHA-256 and 27,013 records. The original
capture predates the single-final-timestamp fix, so its imported duration differs
by one millisecond; do not present that old metadata as an exact-duration match.

## Independent design review

Impeccable's finish reviewer inspected the native product/design briefs and all
the earlier eleven-screen set. Four material findings drove revisions: persistent
recording actions, unobstructed labelled route endpoints, named replay-position
semantics, and visible ETA assumptions. This is not a production or accessibility
certification. Font scaling, rotation, permissions, failure states and future core
integration need their own runtime coverage. The initial large-text and landscape
captures are bounded checks, not a complete device matrix.

## Visual and environment status

- The observed dark three-button contrast issue is resolved in the current
  captures: system buttons have a dedicated daylight-neutral background in both
  app themes. The app still requests theme-appropriate gesture-bar appearance;
  gesture navigation and the wider device matrix are not certified by this check.
- Large-text Drive controls remain visible above the task pane, and Record keeps
  its primary action reachable at 200% font scaling. These are bounded captures,
  not a complete minimum-width, language or accessibility-service matrix.
- During configuration changes the emulator reported a system-server death and
  intermittent screenshot-transfer I/O errors. Storage was not full. Retried
  captures succeeded, but these events must not be silently counted as clean
  lifecycle testing or as proven application-only failures. A later landscape-to-
  portrait change was followed by unavailable ActivityManager/accessibility
  services. `validation/emulator-platform-crash.log` preserves the observed
  platform errors; their cause is undetermined. The emulator was rebooted without
  wiping its application data. The saved landscape image is valid visual evidence,
  but the rotation round trip must not be reported as a clean lifecycle pass.
- After that reboot, System UI presented an unresponsive-system dialog. Selecting
  Wait restored interaction. The retained import and recorded replay were then
  inspected again, and the raw recording still matched its export SHA-256. This
  recovery does not turn the preceding platform failure into a clean test run.
- Two later instrumentation attempts aborted with `System has crashed`; one also
  produced a disconnected emulated-storage endpoint. The logs are retained as
  `validation/gps-ui-platform-abort.log`, `gps-suite-platform-abort.log` and
  `gps-platform-restart.log`. The successful run uses a cold-started emulator,
  the smaller rendering override and no concurrent Gradle daemon. This does not
  establish the cause of the earlier platform failures or certify their repair.
- Visual inspection caught a false invalid-timestamp label when a new fix was
  compared with a cached UI clock tick. Rendering now samples the current
  monotonic clock, and the UI test checks the fresh-fix label after delivery.
- Cold-start testing also exposed an out-of-region GPS origin preventing a local
  preview. `validation/outside-region-before-fix.log` records that failed run;
  the final implementation previews from its labelled included-area origin and
  prevents starting guidance from outside the included map. It does not add a
  new region, expand the road graph or validate turn restrictions.
