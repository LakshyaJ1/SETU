# Android map crash fix

## Delivered build

- APK: `dist/android/SETU-demo-mvp.apk`, 155,155,673 bytes.
- SHA-256: `91c7840a99ad4ade9cf63700fd0627a0670e9d1638ce5fbd94032553cc480e84`.
- Installed APK hash matches on the CPH2467 phone, Android 15 / API 35 / arm64.
- Branch: `demo-mvp/position-tracking`, base commit `d566585`, with uncommitted changes.
- Updated in place without clearing app data; all 15 original raw recordings retain
  their pre-install SHA-256 hashes. No recording was started or stopped by these checks.

`build-evidence.json` contains the artifact identity and check summary. This is a
debug/testing APK, not a production release or proof of full-drive positioning accuracy.

## Diagnosis and change

The preceding NCR APK loaded the entire 137 MB drawing GeoJSON into MapLibre.
Phone exit records included low-memory termination and a renderer finalizer taking
longer than its 10-second watchdog. Renderer lifecycle and memory callbacks also
needed correction; opening the map at whole-region scale hid useful street detail.

The app now renders 11,159 local vector tiles, each below 500,000 bytes. A verified
48,486,133-byte archive expands into private cache once. Tile geometry is generalized
by zoom; this does not reduce the geographic envelope or the separate routing graph.
The app opens at street level, balances renderer lifecycle calls, and does not flush
renderer caches whenever the map leaves composition. Readiness waits for a completed
render frame rather than querying a native renderer before it exists. Route searches
are serialized and respect coroutine cancellation checkpoints.

An intermediate test revision exposed a native crash by querying rendered features
too early. Both the production readiness path and the test were corrected; the
results below belong to the corrected final APK, not that failed candidate.

## Final verification

| Check | Result |
| --- | --- |
| Debug app/test APK build | Passed |
| JVM unit tests | 32 passed, zero failures/errors |
| Python map/estimation regressions | 49 passed; see `python-tests.log` |
| Focused phone suite | 33 passed, 1 assumption-skipped; 47.426 seconds |
| Android lint | Zero errors, 16 warnings |
| APK signature / 16 KiB ZIP alignment | Both passed |
| MainActivity street-level map | Visually checked on the final installed APK |
| Phone exit records after final installation | No new crash; install/instrumentation stops only |

`phone-regression-tests.log` covers `MapRenderingTest`, `SensorFallbackTest`,
`NativeEngineTest`, `NativeFilterTest`, `TripStoreTest`, `PositioningDemoTest`, and
`MapPackStoreTest` except `includedNcrCoversCitiesAndRoutesShahdaraToMait`. The skipped
test is the opt-in physical-sensor replay, not a passed real-drive test.

The renderer stress test checks actual rendered road features at Shahdara, MAIT,
Noida, Ghaziabad, Meerut and Gurugram, with six zoom/theme/disposal cycles. It waits
12 seconds after the final disposal to observe the finalizer-watchdog interval.
`renderer-metrics.json` records 245,827–247,228 KiB PSS after disposal/GC. These are
not peak memory measurements and exclude a loaded full routing graph. Its legacy
`coldLoadMs` field is **1,383 ms for the first map render in that test process on an
already-prepared tile cache**, not a cold-install/extraction measurement.

## Scope and remaining limitations

- Map sources are local files and glyphs are bundled assets. This final phone run
  did not deliberately disable Wi-Fi, mobile data or Location.
- A previous tiled candidate showed the blue Shahdara-to-MAIT sample route over
  the basemap and survived tab switching. Those manual route captures are not
  final-APK evidence; the final run verifies renderer cycling and the street map.
- First-time route preparation can still take minutes while the large graph loads.
  Prepare the route before presenting; map tiles do not accelerate graph parsing.
- A broader preliminary run failed the separate Bengaluru
  `OfflineMapTest.includedDestinationsHaveDrivableRoutes` connectivity test. It is
  outside this crash fix and remains unresolved; do not describe all device tests
  as passing.
- Oversized legacy GeoJSON drawing packs above 32 MiB are rejected unless they
  match the bundled tiled region. Import limits alone are not rendering guarantees.
- Sensor fallback still depends on calibration and its existing 10-second,
  150-metre uncertainty and 100-ms IMU-gap limits. A continuous GPS-free drive from
  Kirti Mandir to MAIT remains unverified.

Device-clock timestamps in raw artifacts are not an authoritative build date.
Private screenshots, exit records and recording hashes remain in ignored local
`.shots/map-crash/`; they are not published with this report.
