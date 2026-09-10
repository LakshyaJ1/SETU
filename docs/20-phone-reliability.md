# Phone reliability and offline tile integrity

## Failure reproduced on the connected CPH2467

The older routing preview's `cache/vector-maps/<archive-hash>` directory contained
only 2,057 files, including its `complete` marker, instead of 11,159 tiles plus
the marker. The Connaught Place detail tile `13/5852/3415.pbf` was absent even
though its 94,470-byte payload exists in the packaged archive. An overview could
still render while street-detail maps stayed blank. The real map-rendering test
failed on the phone, including on an isolated retry. This was not a RAM-limit
failure or evidence that the drawing archive lacked Delhi coverage.

The root cause was treating a marker in disposable cache storage as proof that
all of its sibling files still existed. The marker was not an inventory check.

## Repair and integrity contract

- Prepared tiles now live under private `files/offline-vector-maps`, not cache.
  No user recording or old cache folder is deleted during the migration.
- Bundling creates a deterministic `tile-index.json` from the unchanged archive.
  Each entry binds a bounded tile path, byte length and SHA-256. `tiles.json`
  binds the index hash, while the index binds the archive hash.
- Every source open validates the signed-APK inventory and every required tile.
  A surviving marker cannot hide a missing, truncated or same-length corrupt file.
- An invalid pack is rebuilt in a separate staging directory from the bundled
  archive, with archive and per-tile integrity checks. The directory is published
  only after all entries match. Normal operation remains completely local.
- Persistent preparation does not mean data survives uninstalling or clearing
  application data. Those actions still remove private recordings and map files.

The phone test removes a detail tile, truncates it, and flips a byte without
changing its length. Each reopen restores the original bytes. A real renderer
test then checks roads at six NCR locations across zooms, themes and disposal.
Checking all hashes has a measurable warm-open cost; it is not described as free.

## Routing and output cadence

A conservative block-bounds index now prunes road segments before exact snapping.
It preserves long segments crossing the query area, both directed edges, the
250-metre access limit, cancellation and connected-road entrance fallback. The
NCR index uses 906,912 bytes and is built once per loaded graph. It is a coarse
spatial index, not a full routing hierarchy, turn-restriction database or road
matching estimator. A* working memory and first-load validation still exist.

The live estimator publishes at 100 ms intervals rather than 200 ms, provided
aligned input is available. Pairing-drop counts are retained in native state
records. Deterministic tests separately check GPS-supported, sensor-only and
GPS-recovery output intervals. This does not extend the ten-second outage limit
or establish ten-hertz physical position accuracy without a valid alignment.

## Physical testing boundary

The hardware recording test uses actual accelerometer/gyroscope callbacks and a
foreground recording service, backgrounds the application for fifteen seconds,
and checks locally saved timestamps. The requested radio-off run disables Wi-Fi,
mobile data and the location master switch, then restores their prior states.
It disables optional model sharing and restores application settings afterward.
It does not inject a successful GPS calibration or call raw IMU capture a valid
absolute position. Test-owned recordings are separate from existing user trips.

An initial lifecycle test used `ActivityScenario.moveToState` to background and
resume the activity; resumption timed out. The revised test backgrounds the actual
task. A count-only check initially passed, but the stronger last-sample-age check
exposed a real problem: the phone's OplusHansManager froze the entire process
about eleven seconds after SETU left the screen. The recording foreground service
and partial wake lock were still registered. Raw callbacks and the instrumentation
thread stopped together; bringing SETU forward resumed them. A separate recording
started through the real UI reproduced this outside instrumentation.

The phone initially had Battery saver on and SETU's background allowance off.
Allowing background activity did not solve the freeze. A further test with Battery
saver off, background activity allowed, Wi-Fi/data off and location off also
failed: a requested fifteen-second interval took 144,918 ms, and its last sensor
sample was about 134 seconds old. This is an unresolved device/background blocker,
not a successful blackout navigation trial. Settings now explains the battery
controls and links to App info, but does not claim those controls guarantee capture.
The native engine already rejects large IMU gaps instead of integrating across them.

Actual-hardware tests are opt-in with `-e physicalHardware true`. Foreground and
background capture are separate tests, with elapsed-time, sample-age, monotonicity
and raw IMU gap checks; a sensor count alone is not a continuity assertion. Radio
and Battery saver changes used for testing are restored afterward. Background
capture remains unaccepted even if foreground raw capture passes. No global OEM
freezer, security setting, or permission protection was disabled.

After the owner unlocked the phone, the separate thirty-second foreground test
passed with GPS, Wi-Fi and mobile data off and Battery saver still on. Actual
accelerometer callbacks achieved 199.83 Hz; the largest accelerometer/gyroscope
timestamp gap was 5.006 ms and the final published sample was 67.05 ms old. The
recording saved successfully with sharing disabled and zero native pairing drops.
This closes the short foreground raw-capture check, not background continuity or
GPS-denied positioning accuracy. Exact logs and measurements are linked in the
APK-specific verification ledger.

UI tests preserve existing preferences and avoid re-granting permissions that the
user already granted. A pre-existing verification map is protected rather than
overwritten by the map-import workflow. No existing trip is a disposable test fixture.

The exact APK, final logs, measurements, skips and remaining limitations belong
in `verification/android/phone-reliability/README.md`. No full-production or
GPS-denied real-drive acceptance claim follows from this increment.
