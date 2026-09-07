# Delhi offline map

## Coverage and purpose

The Delhi region is an OpenStreetMap street-map extract for the geographic
envelope **28.39–28.91° N, 76.83–77.36° E**. It covers the NCT's extent and some
adjoining areas; it is not an administrative-boundary dataset. It includes OSM
streets across the envelope, including residential and service roads, together
with mapped park and water polygons represented by closed ways.

The map retains all **227,111 extracted street segments**, grouping identically
styled lines and simplifying their shape within approximately one metre. The
graph for route previews contains **20,188 main-road ways** and **115,314 node
references**; residential, service and living-street roads remain visible but
are not part of that preview graph. Shared graph junctions and one-way flags
are retained. Local tracking does not require a route or a main-road starting
point.

The renderer payload is 24,068,223 bytes and the graph is 6,069,788 bytes, inside
the existing 24 MiB / 8 MiB file budgets. There are 928,725 visual coordinates;
the app's bounded coordinate/way counts are raised to one million / 25,000 to
accept this compacted data. This is not an unbounded memory-limit increase.

This is map coverage, not a guarantee that every lane, address or destination
is present. Buildings and relation-only polygons are omitted. English or other
names supported by the app's existing offline glyphs are retained; unsupported
labels are not silently transliterated. Places include a curated central preview
and OSM localities/stations. Turn restrictions, closures, conditional access and
safety-validated driving routes remain outside the current routing engine.

Delhi is included alongside Bengaluru Central. Existing map selections are
preserved across upgrades. In **Settings → Offline area**, choose Delhi's
**Use this map** action. Both included maps remain available offline and cannot
be removed; eight additional imported packs can still be retained.

## Reproducible source

The source is Geofabrik's Northern Zone OSM PBF, with data timestamp
`2026-09-06T20:21:35Z`, rather than BBBike's smaller New Delhi rectangle. The
downloaded PBF is 222,921,802 bytes; its publisher MD5 was verified before use.

- Source SHA-256: `42cf5b71f0acfab938f3af70a68fc594e5b10828ed400563da68eca5704c06ab`.
- Source page: `https://download.geofabrik.de/asia/india/northern-zone.html`.
- Copyright and ODbL terms: `https://www.openstreetmap.org/copyright`.
- Region configuration: `tools/map-regions/delhi.json`.
- Offline-only builder: `tools/build_osm_region.py`.

The builder uses the optional `maps` development extra (pyosmium) to read a
locally downloaded PBF. It does not fetch data or contact a tile service.
Generated source extracts belong in ignored `data/raw/` and `data/interim/`;
distribution archives belong in ignored `dist/maps/`. The final APK includes
the region's renderer data, graph and metadata under `assets/regions/delhi/`.

```powershell
python -m pip install -e ".[maps]"
python -m tools.build_osm_region data/raw/maps/northern-zone-2026-09-06.osm.pbf tools/map-regions/delhi.json data/interim/delhi-region --pack dist/maps/delhi.setumap
python -m pytest tests/test_osm_region.py tests/test_map_pack.py
```

Use a new output directory/archive for each build. Retain the generated source
timestamp, source hash and summary with the distribution; a download time is
not the map data's timestamp.

## India-wide coverage

India is **not** represented by an empty placeholder or by stretching Delhi's
coverage rectangle. On September 7, 2026, Geofabrik listed its country-wide OSM
PBF at approximately 1.6 GB. That is source data, not an estimate of a finished
offline app map's size. The current format accepts local regions spanning at
most two degrees, with bounded in-memory GeoJSON and a local road graph.

Whole-India offline street detail needs zoom-indexed vector tiles and regional
routing/search partitions, plus download/resume/integrity management. Simply
raising RAM limits or loading the whole country into the current city parser
would not provide a dependable demo. Delhi is the immediate supported region;
country-wide offline navigation is not claimed by this change.

## Delivered build and phone verification

The Delhi build was installed on the authorized CPH2467 phone running Android 15
on September 7, 2026. Delhi is selected, and the selection survives an app
relaunch. The Connaught Place to India Gate sample produces a 4.6 km route preview;
its replay remains explicitly labelled synthetic. Real GPS was separately
observed over Delhi street detail, with 91 non-mock positions inside the map
envelope in a saved 136.066-second recording. This stationary smoke test is not
a field-accuracy or movement benchmark.

- APK: `dist/android/SETU-demo-mvp.apk`, 62,228,039 bytes.
- APK SHA-256: `86ae1405bc5f88c9acaf8d6c6b747f0244882fdd567f12c9a5ac04bcf2c7c562`.
- Portable map: `dist/maps/delhi.setumap`, 8,727,331 bytes (about 8.3 MiB).
- Pack SHA-256: `084ce38e69a5722eaf81f6f61c5eed062b10969e01b8b0ebbeb2adc6770dab13`.

The map is already inside the APK; importing the archive is unnecessary on this
build. The archive is provided for redistribution and uses the updated reader's
one-million-coordinate limit. Older APKs with the 600,000-coordinate limit will
reject it rather than loading unbounded data. Install APK updates with
`adb install -r` to retain trips and settings; do not clear app data.

Validation passed: 15 map-builder/packager Python tests, 15 JVM tests, 13 focused
physical-phone instrumentation tests, debug assembly and APK signature/alignment
checks. Lint reports zero errors and 16 warnings. The full stress suite and a
moving outdoor drive are not claimed. See `verification/android/delhi/README.md`
for the exact build, test log, capture hashes and privacy-preserving live-check
summary. All five pre-existing recording files remain byte-identical.

Map coverage also does not resolve the physical phone's missing heading-accuracy
input. Live GPS tracking and the explicitly simulated native-gap presentation
remain distinct, as documented in `14-demo-mvp.md`.
