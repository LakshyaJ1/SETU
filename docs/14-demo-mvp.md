# Android presentation MVP

## Delivery boundary

This is a demonstrable positioning application, not a release claim for the full
SETU architecture. The presentation has three distinct sources of evidence:

1. **Live tracking:** the phone's current GPS, or the opt-in native GPS/IMU
   estimate when aligned and fresh. The map follows the position and retains a
   bounded display trail while the foreground service records the journey.
2. **Positioning demonstration:** controlled synthetic sensor inputs processed
   by the packaged native engine. This demonstrates its input/output integration,
   uncertainty propagation and GPS reacquisition, not physical driving accuracy.
3. **Saved journeys:** recordings collected on the device, with timestamped GPS
   replay and explicit export/import. A sample-route animation remains separately
   labelled as synthetic replay.

AI/ML training and weights remain the teammate's responsibility. The existing
model-server boundary is not an inference-to-filter integration. The demo does
not relabel native inertial processing as trained-model output.

## Builds for testing

The pre-demo work was checkpointed on `demo-mvp/position-tracking` at `d4aceca`.
The unchanged, built debug APK is retained locally as:

`dist/android/SETU-checkpoint-d4aceca.apk`

The presentation build is delivered locally as `dist/android/SETU-demo-mvp.apk`.
Generated APKs are intentionally ignored by Git. Both builds use application ID
`com.setu.navigator`; install with `adb install -r` to preserve existing data.
Do not uninstall or clear app data to switch between these debug builds.

Open `android/` in Android Studio. Build prerequisites and the optional local
Gradle output directory are documented in `android/README.md`. This workspace's
verification uses `%LOCALAPPDATA%\SETU\android-build` to avoid replacing locked
native build outputs inside OneDrive.

## Presentation sequence

### 1. Introduce the live product

Open Drive and choose **Track my position**. Grant precise location and, when
requested, notifications. Obtain a GPS fix outdoors before the presentation.
The session records without requiring a destination. Show the coordinates,
speed, source label and reported uncertainty; unknown values are not zeros.

Pan to explore the map and use **Follow position** to resume automatic following.
The blue line contains observed/estimated positions, not a pre-planned route.
Gaps longer than three seconds and changes of source break the display trail.
The display retains at most 1,200 samples; the recording is not truncated by
that display limit. The foreground notification can stop and save the session.

**Sensor fusion preview** explicitly enables the native estimate. It requires
usable phone orientation, synchronized acceleration/gyro and fresh GPS for
alignment. GPS remains the fallback when native output is unavailable. The
native 95% filter radius is not Android's GPS accuracy and is not field validation.

If **Heading accuracy unavailable** appears, the phone is not supplying the
heading-uncertainty input required for native alignment. GPS tracking and raw
recording still work. Do not present the live view as GPS-denied fusion in that
state; use the explicitly simulated demonstration for the native gap sequence.

Tracking can continue outside the active offline area, but street detail cannot.
Select the included Delhi map for a Delhi presentation, or use Bengaluru Central
for the original demonstration. Delhi's street coverage includes local roads,
but its route previews use a smaller main-road graph. See `15-delhi-offline-map.md`.
Do not confuse an offline-area preview with the phone's position.

### 2. Demonstrate the GPS gap

Stop and save any live recording, return to Drive, and choose
**Demo GPS loss & recovery**. The 24-second sequence runs without GPS reception:

- **Lock:** simulated GPS updates and 100 Hz motion samples initialize the engine.
- **GPS loss:** GPS inputs are withheld from 6 to 14 seconds. The last GPS marker
  stays behind while the engine propagates the position and its uncertainty.
- **Recovery:** GPS inputs return and the engine corrects its estimate.

Use Lock, GPS loss and Recovery to pause at a presentation moment. The timeline,
play/pause and playback speed remain available. Rotation retains the current
demo and paused timestamp. Light and dark themes use the same data.

Green denotes the simulated reference path, blue the engine's estimate and
amber the last supplied GPS position. The reference is a controlled test track,
not a road-matched driving route. Frames are calculated on-device through JNI
and then replayed; this view is not a live phone-sensor or accuracy demonstration.
It never writes simulated samples into the user's live recordings.

The eight-second example is deliberately inside the engine's existing short-gap
boundary. Longer outages, large uncertainty and missing sensor input can withhold
the live estimate. Do not describe this as minutes of validated GPS-denied driving.

### 3. Close the loop with a saved journey

In live tracking, **Stop & save journey** opens Trips. Open the saved journey,
inspect its duration/path, replay it, then demonstrate export if appropriate.
Export is a deliberate user action; recordings stay on the phone by default.
The Record tab describes synchronized acquisition without the former
"No AI model required" presentation copy.

Use destination search and the separately labelled sample route to demonstrate
offline navigation UI. Map-pack import, selection, removal and checksum-verified
download are covered in `docs/13-offline-map-packs.md`.

## Verification and release limits

Current Delhi build evidence is indexed in
`docs/verification/android/delhi/README.md`: 13 focused phone tests, a rendered
Delhi route, persisted region selection and real non-mock GPS over local streets.
Earlier presentation captures and emulator workflows remain indexed separately in
`docs/verification/android/demo-mvp/README.md`. The complete instrumentation suite
has not been rerun successfully on this build. These checks do not establish
physical-phone accuracy, battery life or road safety.

Full road constraints, mount calibration, broader signal frontends, model-output
fusion, production map coverage/routing and extended physical-drive validation
remain on the full-product ledger in `docs/11-android-delivery.md` and
`core/STREAMING.md`. Rehearse on the actual presentation phone before presenting.
