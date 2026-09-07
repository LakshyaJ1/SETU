# Presentation MVP evidence

This is historical **pre-Delhi** build evidence. Its APK is preserved as
`dist/android/SETU-phone-before-delhi-44052b3.apk`; references to the current build
in this snapshot mean that APK, not the newer `SETU-demo-mvp.apk` alias.
The Delhi map update and its separate phone checks are in `../delhi/README.md`.

This directory keeps the presentation build separate from the earlier Android
baseline. `build-evidence.json` identifies the installed phone build and the
checks actually completed. Capture sidecars identify the installed APK and
unaltered PNG hash; earlier emulator captures do not verify a newer APK.

## Physical phone rehearsal — September 7, 2026

An authorized USB-connected CPH2467 running Android 15 / API 35 / arm64-v8a was
used without installing a mock location provider or changing network settings.
The current APK builds successfully, passes 15 JVM tests and the two native
presentation tests on this phone, and has zero lint errors (16 warnings).

| Current-build capture | What was observed |
|---|---|
| `phone/01-native-lock.png` | Native presentation at the two-second simulated GPS-lock phase |
| `phone/02-native-gap.png` | Simulated GPS withheld; native output continues with growing uncertainty |
| `phone/03-native-recovery.png` | Simulated GPS returns and the native uncertainty contracts |
| `phone/04-heading-readiness.png` | Real phone's missing heading-accuracy input is explicitly identified |
| `phone/05-record-readiness.png` | Physical accelerometer/gyro detected at approximately 200 Hz; revised Record copy |

Actual GPS tracking, stop/save and advancing saved-journey replay were exercised
on the current APK. The short stationary recording contains 8,894 sensor/GPS
records and 12 GPS positions, all explicitly non-mock. Its duration is 12.682
seconds. A preceding 78.276-second check on the earlier phone APK contains
54,905 records and 78 non-mock GPS positions. These are integration checks, not
measured walking/driving accuracy or validated distance.

Precise-location screenshots remain in the ignored `.shots/phone-review/`
directory, with APK/hash sidecars, rather than tracked evidence. Both pre-existing
user recordings remain byte-identical. Verification recordings were retained;
no data was cleared and no recording was left running at handoff.

**Live GPS-denied fusion is not validated on this phone.** Every recorded
rotation vector reported heading accuracy `-1` (unavailable), despite a high
sensor calibration code. The native alignment requirement remains unchanged:
the app now explains **Heading accuracy unavailable** rather than misleadingly
waiting for GPS/IMU that are already arriving. It does not invent heading
uncertainty to force a native position. `phone/heading-readiness-before.json`
records the diagnostic evidence without coordinates. The included offline area
also does not cover this phone's test location; blank street detail there is
not a lost GPS fix.

## Presentation capture checklist

The following captures are produced by the automated presentation workflows.
The final build's complete capture set has not yet been collected into this
directory; filenames below are a checklist, not a completed verification claim.

| Capture | What it demonstrates |
|---|---|
| `42-positioning-demo-lock.png` | Native engine initialized from controlled synthetic GPS/IMU |
| `43-positioning-demo-gap.png` | GPS withheld; native inertial output; paused state retained after Activity recreation |
| `44-positioning-demo-recovery.png` | Synthetic GPS accepted again after the gap |
| `45-positioning-demo-dark.png` | The same presentation in the dark theme |
| `46-live-position-trail.png` | Foreground tracking with controlled mock Android locations; the test also checks the actual map camera target |
| `47-tracked-journey-saved.png` | Stop/save opens Trips and the saved journey is opened through the UI |
| `48-record-presentation-copy.png` | Revised Record-tab copy and timestamp-aware GPS readiness |
| `49-tracked-journey-replay.png` | The saved test journey is replayed through the UI |

Evidence must be screenshots of the running application, not design mockups.
Controlled inputs must remain deliberately labelled. Neither synthetic error
nor a visible moving marker establishes physical-phone accuracy.

The current phone test's output is `phone/positioning-demo-metrics.json`, with
its two-test result in `phone/native-engine-tests.log`. It checks that accepted
GPS counts do not increase during the
eight-second gap, the estimate keeps moving, uncertainty grows, and GPS
corrections resume. Its small synthetic error is not a deployment benchmark
and must not be presented as one.

## Baseline and discovered faults

`00-checkpoint.png` and its sidecar show the unchanged build checkpointed at
`d4aceca`, before the presentation changes. That APK is retained in
`dist/android/SETU-checkpoint-d4aceca.apk`.

The first focused run was interrupted by a `system_server` watchdog during GNSS
shutdown. `first-run-gnss-watchdog.log` shows the foreground GNSS stop waiting for
the status-listener lock while a binder thread holds that lock and waits for
`stopSvStatus`. The app now unregisters measurements and satellite callbacks
before removing location updates. A regression workflow repeats stop/start eight
times. This avoids the observed teardown ordering; it is not a universal claim
about Android GNSS implementations.

The first full-suite run was killed for low memory during map switching. Its
output and Android exit reason are retained in `before-memory-handling-*`.
Map views now receive Android memory-pressure callbacks and release their
native cache on disposal, but this did not clear the long-run stress failure.
The `before-direct-map-source-*` files retain that second run. A direct map-URI
experiment also failed to resolve it and introduced a test-idling failure; it
was reverted. Its output is preserved in `map-uri-experiment-tests.log`.

Neither a complete monolithic run nor the proposed isolated-process rerun has
passed on the current APK. Earlier focused passes and the two phone-native
tests do not establish that result.
At the user's request, further 2 GB emulator stress work is deferred in favor
of the physical-phone checks described above. A short successful phone run and
more device RAM alone do not establish long-session stability.

Only recordings created by verification may be removed by its cleanup. The two
pre-existing user trip IDs remain outside cleanup. The interrupted test's
recording ID was `4082d5ef-609c-4d7e-9320-be50c6c0cdbb`, with header name
`Position tracking`, start time `1788792426412` and an emulator device label.

## Rehearsal boundary

The initial emulator is API 35 x86_64 with a 720 × 1600 / 280 dpi viewport. The
phone is API 35 arm64-v8a with a 1080 × 2400 viewport and font scale 1. Its JNI
presentation, GPS acquisition, recording and replay are now exercised, subject
to the heading limitation above. Follow `docs/14-demo-mvp.md` for rehearsal.
Long-drive accuracy, thermal/battery behavior, advanced road constraints and
trained-model integration remain outside this presentation sign-off.
