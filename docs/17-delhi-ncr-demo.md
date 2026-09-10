# Delhi/NCR demonstration build

## Included map and route

- Bundled **Delhi & NCR**, revision 2, retains the existing `bundled-delhi` selection.
- Geographic envelope: latitude 26.5–30.2, longitude 75.25–78.75. This is a large
  regional rectangle, not an exact administrative boundary or a whole-India map.
- Three Geofabrik/OpenStreetMap extracts supply Northern, Central and Western
  Zone data; the Central Zone supplies the eastern NCR streets. Source timestamps
  are `2026-09-06T20:21:35Z`. Source hashes and counts are retained in the build evidence.
- 1,039,544 public drivable ways, 3,185,592 graph nodes, 7,255,057 directed edges
  and 300 searchable places. Public residential/service roads are included;
  private roads are excluded. Drawing/routing simplification is about 3/5 metres.
- `dist/maps/delhi-ncr-v2.setumap` is the complete portable pack. The intermediate
  `delhi-ncr-incomplete-north-west.setumap` lacks eastern data; do not distribute it.
- The crash-fix build renders **11,159 local vector tiles**, not the complete
  137 MB GeoJSON document. Each tile is below 500,000 bytes; the 48.5 MB archive
  expands once into private app cache with checksum, size and path validation.
  Low zooms generalize road detail; zoom in for local streets. Geographic coverage
  and the routing graph are unchanged. The initial map now opens at street level.
- First tile preparation takes several seconds. The original JSON-graph builds
  also needed a long first route parse. The routing preview instead prepares a
  compiled, checksum-verified graph and maps it read-only; first extraction and
  later checksum/validation still take time. Prepare a route before presenting.
  Format and verification scope: `19-compiled-road-graphs.md`.

The saved preview runs from a public **Naveen Shahdara area point** to **MAIT,
Sector 22, Rohini**. It is not a verified Kirti Mandir entrance. For the actual
Subhash Park/Road 60 journey, begin with a fresh GPS fix at the temple.

Planned routes are blue with a contrasting outline. Dashed access links indicate
the gap between a requested point and the nearest public road; they do not assert
a safe/drivable entrance. Maneuvers now follow progress along road segments rather
than jumping ahead at the midpoint between vertices. Losing GPS no longer forces
the map to zoom out to the entire journey. None of this snaps a measured position
onto the planned route or simulates live movement.

## Sensor readiness and GPS loss

Enable **Sensor fallback** before the drive. The readiness panel distinguishes
disabled, calibrating, initialized, estimated and withheld states. Keep Location
on until alignment is initialized. A magnetic disturbance can prevent checked
compass initialization; the new experimental GPS-motion alignment instead uses
relative game rotation and observed GPS velocity changes during acceleration,
braking and turns. This requires real motion and a starting GPS fix, not an
internet connection. New recordings retain heading/readiness diagnostics even
when the estimator cannot produce a position.

The existing limits remain: at most **10 seconds since the last accepted GPS
fix**, at most **150 m modeled 95% radius**, and no IMU gap above **100 ms**.
Any limit can stop prediction earlier. Synthetic tests do not establish real-road
accuracy. Continuous GPS-free navigation for the full temple-to-college drive
is **not verified or promised**. Do not operate the app while driving; a passenger
should handle the demonstration, and an independent navigation aid should remain
available.

## Reproduction and delivery

`tools/map-regions/delhi-ncr.json` defines the region. Build it with
`python -m tools.build_osm_region`, supplying the Northern PBF and both other PBFs
through repeatable `--additional-source` arguments. Package it with
`python -m tools.build_map_pack <region-directory> <new-output.setumap> --android-assets android/app/src/main/assets/regions/delhi`.
Existing portable packs are never overwritten by this command.

For the tiled Android build, first run `python -m tools.build_map_tiles
<region-directory> <new-tile-directory> --tippecanoe <tippecanoe-executable>`.
Then pass `--vector-tiles <new-tile-directory>` to `build_map_pack` as well. This
omits the whole-region drawing asset from the APK while keeping the complete
portable pack. The tile build uses Tippecanoe; Android needs no tile server or
additional runtime dependency. Other large legacy GeoJSON packs are rejected by
the renderer above 32 MiB unless they match the bundled tiles, rather than risking
another memory crash.

The testing APK remains `dist/android/SETU-demo-mvp.apk`. The preceding NCR build is
preserved as `dist/android/SETU-ncr-6780e53.apk`. Exact hashes and
checks for the crash fix are in `verification/android/map-stability/README.md`.
The initial NCR build's results remain in `verification/android/delhi-ncr/README.md`;
that earlier build subsequently exhibited renderer timeouts and memory pressure.
