# Delhi map phone verification

This is the original Delhi build, preserved as `dist/android/SETU-delhi-86ae140.apk`.
The later sensor-fallback build has separate evidence in `../sensor-fallback/README.md`;
the older screenshots and hashes below have not been relabelled.

Verified on September 7, 2026, on an authorized USB-connected CPH2467 running
Android 15 / API 35 / arm64-v8a, at 1080 × 2400 and font scale 1.
`build-evidence.json` identifies the installed APK, map archive and actual checks.
This evidence supersedes the pre-Delhi build without relabelling its captures.

## Completed checks

- Debug app and test APKs build; 15 JVM tests pass. Lint: zero errors, 16 warnings.
- All 15 focused Python map-builder/packager tests pass, including the optional
  pyosmium PBF extraction check; formatter and linter checks pass.
- `MapPackStoreTest`, `OfflineMapTest` and `PositioningDemoTest` pass on the phone:
  **13 tests** in 4.826 seconds. See `phone-map-tests.log`.
- Delhi is included beside Bengaluru, protected from removal, activated through
  the UI and still selected after a no-recording app stop/relaunch.
- The sample route renders on Delhi streets and replays as **Explore Delhi**,
  with an explicit synthetic label and a displayed distance of 4.6 km.
- A separate physical recording contains 95,330 records and 91 GPS positions,
  all explicitly non-mock and within the Delhi map envelope. Its duration is
  136.066 seconds. Real street detail and a GPS marker were visually checked.
- The physical recording ends cleanly through the app's normal `STOP` service
  action, invoked under the app UID. The new trip is retained. All five earlier
  raw recordings retain their original SHA-256 hashes; no recording remains active.

The archive/build details, source provenance and route-graph limitations are in
`../../../15-delhi-offline-map.md`. The runtime uses local assets, not online
tile requests. Network settings were not changed for this phone check, so it is
not a separate airplane-mode acquisition test.

## Captures

All PNGs are unaltered device screenshots; JSON sidecars contain their hashes
and the SHA-256 of the APK actually installed at capture time.

| Capture | Observation |
|---|---|
| `01-delhi-included.png` | Delhi and Bengaluru are both included; Delhi has a selection action |
| `03-delhi-explore.png` | Drive renders the selected Delhi map |
| `04-delhi-sample-route.png` | Labelled synthetic Delhi route and replay controls |
| `07-delhi-loaded-preview.png` | Loaded city overview, attribution and source snapshot |
| `08-delhi-persisted-after-relaunch.png` | Delhi remains the active map after process restart |

`02-delhi-map-overview.png` retains an initial blank map frame; it is not evidence
of a loaded map. The later overview and relaunch captures above show the rendered
geometry. Allow the city data to finish loading before starting the presentation;
these captures do not establish a startup-time benchmark.

The real-position capture and raw verification recording are kept only under
ignored `.shots/delhi-review/`, not in tracked evidence. The manifest contains
aggregate counts and coverage booleans, not precise user coordinates.

## Boundaries

Delhi is a bounded street-map extract, not whole-India coverage or a surveyed
administrative boundary. Local lanes are drawn, but route previews use the
main-road graph and do not implement turn restrictions or live closures.
The phone still reports **Heading accuracy unavailable**; GPS fallback is not
native GPS-denied fusion. No heading safeguard was relaxed by this update.
The full instrumentation stress suite, moving-road accuracy, long sessions,
battery/thermal performance and network-disabled GPS acquisition are unverified.
The small synthetic native test error must not be presented as field accuracy.
