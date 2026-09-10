# Android offline map packs

## Scope

`setu.map.v1` packages the current local GeoJSON renderer, place search and
one-way-aware road graph. The Android manager supports document import, direct
download, explicit selection and removal. This is not PMTiles/MBTiles support,
a worldwide map service or a production route-safety claim. Runtime verification
and remaining work are recorded separately in `11-android-delivery.md`.

Bengaluru Central and Delhi are included and cannot be removed. The Delhi-wide
street map has main-road route previews; see `15-delhi-offline-map.md` for the
exact extent, source and limitations. Existing selections are preserved.
Installing another
region does not select it. The user explicitly chooses **Use this map**. A newer
revision is installed alongside the previous revision, so the user can switch
back before removing the old one. Equal revisions and downgrades are rejected.
Up to eight imported packs may be retained in addition to the included regions.

## Package contract

A `.setumap` is a ZIP containing exactly three root-level regular files:

| File | Maximum uncompressed size | Contents |
|---|---|---|
| `manifest.json` | 65,536 bytes | Metadata, named places and payload hashes |
| `city.geojson` | 160 MiB | Local GeoJSON FeatureCollection |
| `roads.json` | 256 MiB | Connected road-node graph |

Imports and downloads are capped at 200 MiB compressed. Directories, extra files,
duplicate names, absolute paths and traversal names are rejected rather than
normalised. JSON nesting is capped at 16; geometry and roads are read incrementally
instead of constructing an object tree for the complete regional graph.
Imports stage in app-private cache, validate before installation and atomically
rename into an app-generated UUID directory. Failure or cancellation cleans
that operation's staging data without replacing the selected map. Process-death
cleanup of abandoned staging directories is still a hardening task.

The manifest fields are shown in
`android/app/src/androidTest/assets/map-fixture/manifest.json`. That file is a
**synthetic verification fixture**, not real map coverage. Required fields:

- `schema`: exactly `setu.map.v1`; `id`: stable lowercase slug; `revision`:
  integer from 1 to 1,000,000.
- `name`, `summary`, `previewLabel`: user-facing area and route-origin labels.
- `bounds`: **south, west, north, east**. Latitude/longitude are degrees. A local
  region spans no more than four degrees on either axis and cannot cross the
  antimeridian in this version.
- `center`, `previewStart`: **longitude, latitude** pairs inside the bounds.
- `places`: 2–2,000 entries with unique slug `id`, `name`, `detail` and `point`
  in longitude/latitude order inside the bounds.
- `demoDestination`: one of the place IDs. The graph must yield a connected
  preview route of at least 20 metres from `previewStart` to that place.
- `source`, `attribution`, `license`, `sourceUrl`: displayed provenance and an
  HTTPS attribution URL without credentials or a fragment.
- `dataTimestamp`: parseable UTC/offset ISO instant describing the source data,
  not the download or installation time; `limitations`: truthful limitations.
- `sha256`: object mapping `city.geojson` and `roads.json` to their hex SHA-256
  digests. The bundled manifest is trusted as an application asset and does not
  need these payload fields; imported manifests do.

`city.geojson` supports 1–150,000 features and at most 6,000,000 coordinate pairs.
These are the NCR build's budgets; older APKs can reject its larger distribution pack.
Feature properties use `kind` (`road`, `park`, `water`, `building`), optional
`name` and optional `class`. Roads use LineString or MultiLineString; park, water
and building areas use Polygon or MultiPolygon. Coordinates must be numeric,
finite valid longitude/latitude pairs. Lines need two points; polygon rings
need four points and closure. Empty geometry is rejected and at least one
visual coordinate must lie inside the stated coverage. These checks do not
establish topological correctness, correspondence to roads or ground truth.

Map labels must use the offline glyph ranges shipped in
`android/app/src/main/assets/fonts/Noto Sans Regular/`. Unsupported labels are
rejected; publishers can supply transliterated names. Full script coverage and
per-pack glyph delivery remain open. Android UI text is separate from map glyphs.

`roads.json` contains `roads`, an array of 1–1,200,000 ways. Each has a unique numeric
`id`, `nodes` (2–10,000 IDs), matching longitude/latitude `coordinates`, optional
`name` and `oneway` (`no`, `yes`, `1`, `true`, `-1`). Shared node IDs must refer to
identical coordinates. Total node references are capped at 6,000,000; graph storage
allows up to 4,000,000 nodes and 8,000,000 directed edges. Optional `nodeCount` and
`edgeCount` metadata must precede `roads`; indexed node IDs are dense, starting at 1.
The graph
does not implement turn-restriction relations, live closures or full vehicle
access rules. Publishers must not describe it as safety-validated driving data.

## Build a pack

The NCR bundle uses deterministic `.gzip` source assets, `compressedAssets`,
payload hashes and `uncompressedBytes` metadata. The suffix deliberately differs
from `.gz`, which Android's asset merger expands and renames. The portable ZIP
still contains the three ordinary JSON files described above.

The map-stability update instead supplies drawing tiles in `city-tiles.zip` with
`tiles.json` metadata; only roads retain the `.gzip` encoding. The full regional
GeoJSON is not handed to MapLibre. Rendering of other legacy GeoJSON regions is
capped at 32 MiB; a matching NCR payload can reuse the bundled tiles. The larger
import/validation budgets do not imply unlimited whole-document rendering.

The phone-reliability update adds an APK-bound per-tile inventory and prepares
tiles in persistent private files rather than disposable cache storage. Every
source open checks all required tile sizes and hashes; missing or corrupt tiles
trigger verified re-extraction. See `20-phone-reliability.md` for the reproduced
phone failure and repair contract. The drawing archive itself is unchanged.

The routing preview additionally replaces NCR's `roads.json.gzip` with
`roads.bin.gzip` plus `graph.json`. `python -m tools.build_road_graph <roads.json>
<new-output-directory>` builds deterministic little-endian adjacency arrays from
the same source, without fetching data. Pass `--compiled-graph <output-directory>`
alongside `--vector-tiles` and `--android-assets` when bundling. Portable `.setumap`
files retain the original JSON contract. Exact-checksum matching imported NCR
packs may reuse the trusted bundled compiled graph; other imports still validate
and load their JSON graph.

Android expands and verifies the graph into private cache atomically, validates
its structure, and maps read-only buffers instead of constructing millions of
JSON objects and copying all graph arrays to Java heap. Warm loads still check
the full SHA-256 and structure. Corrupt or cancelled preparation is not accepted.
This is a versioned internal compiled cache, **not** the full FlatBuffers routing/
curvature/turn-restriction format in the production architecture.

Routing first tries the nearest directed road segments. Only if they are
disconnected does it consider up to 256 alternative directed segments within
250 metres, first at the destination, then at both endpoints. Access offsets
participate in route selection but remain separate dashed links in the UI; they
are not asserted to be drivable or used to invent a connecting road. Geometry,
one-way directions and requested points are retained. This resolves disconnected
destination spurs without changing the route's underlying road network. It does
not add vehicle access rules, turn restrictions or live closures.

Create a directory containing those three files; the packager fills in `sha256`.
It uses only Python's standard library, performs no network request and refuses
to overwrite an existing output. Android performs the semantic validation.

```powershell
python -m tools.build_map_pack path\to\region path\to\region.setumap
```

The printed SHA-256 covers the entire ZIP. Publish it separately from the direct
download URL. For software verification only:

```powershell
python -m tools.build_map_pack android/app/src/androidTest/assets/map-fixture test-grid.setumap
```

The current OSM data producer is `tools/build_android_region.py`. To package its
output, prepare `manifest.json` from `bundled-region.json`, `city.geojson` from
`bengaluru.geojson` and `roads.json` from `bengaluru-roads.json`. A real map update
needs a new revision and truthful source timestamp; renaming the same data does
not make it fresher. Preserve all applicable source attribution and licences.

## Download, selection and recovery

Open **Settings → Offline area**. Import uses Android's document picker; SETU
copies the selected stream and does not retain broad storage access. Download
requires an explicit direct HTTPS URL and a separately obtained 64-character
SHA-256. Redirects, credentials, fragments, non-200 responses, oversized or
incomplete responses and checksum mismatches are rejected. No hosted SETU map
catalogue or automatic background updater is currently supplied.

Debug builds alone permit HTTP on `127.0.0.1`, `localhost` and emulator bridge
`10.0.2.2`, matching the existing debug network-security policy. Release builds
require HTTPS. Map requests send no trip or sensor payloads. The selected server
still sees ordinary connection metadata such as the request URL and client IP.
A checksum detects changed bytes; it is not a publisher signature or a statement
that the map is trustworthy, current or safe to follow.

The screen exposes progress and cancellation. Cancellation is cooperative;
connection/read waits may take up to the configured 10-second timeout before
returning. Selection persists locally. Payload hashes are rechecked before
activation and startup restoration; an unreadable selected pack falls back to
Bengaluru. A dedicated restoration-warning UX is still pending.

Map mutations are blocked while recording, guiding or replaying. Switching
clears the old route and destination, cancels pending route work, updates local
search and changes map attribution. Removing the active pack is disabled until
another map is selected. Recordings are independent and are never deleted with
a region. Recentring outside the selected region shows its covered area rather
than moving into a blank, unmapped location.

## Verification boundaries

Device tests cover installation, persistence, rollback/fallback, graph use,
revision rejection, corrupt/truncated archives, invalid metadata/geometry,
unsupported glyphs, cancellation and direct HTTP transport checks. UI tests
use the explicitly labelled synthetic grid to exercise selection, search,
route preview, replay lock, rejection and removal. They are not proof of an
additional real city, physical field operation or a production HTTPS publisher.
