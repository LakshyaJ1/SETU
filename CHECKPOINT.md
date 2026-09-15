# SETU — Project Checkpoint

> **Navigation acceptance:** the confirmed target is 90% of GPS-free 10 Hz updates
> within 10 m, including missing estimates as failures, across 10–180 s outages.
> `docs/verification/android/road-stress/README.md` and `metrics.pdf` supersede old
> benchmark claims. All 675 corrected synthetic trials completed; no algorithm
> passes the full matrix. Normal training exports now allow 120 s GPS warmup.
> The final application, independent field validation and website remain open.

> **Current review:** see `docs/21-upstream-review.md` and the walking/stationary
> fixes in `docs/23-walking-fallback-investigation.md`. Sections below are a
> chronological working log, not a consistent current-status snapshot. In
> particular, the initial statements that there are no native constraints or
> bundled models are superseded. NHC, ZUPT, SVO, CTS and local TFLite inference
> are implemented; road-hypothesis estimation and physical acceptance remain
> open. The bundled model has `deployment_approved=false` and failed G4: the
> Android runtime now enforces evaluation-only output rather than fusing it.

> **Scooter follow-up:** `docs/24-scooter-data-review.md` records the three selected
> rides, corrected activity handling and research dataset target. Car constraints
> and the bundled Car-only model do not apply to scooters. Heading availability
> and GPS-free field accuracy remain open; the supplied rides are diagnostic-only.

> Generated 2026-09-12 from a full read of `docs/01`–`docs/20`, `core/`, `android/`, `setu/`,
> `tools/`, plus a live probe of the model endpoint.
>
> **Status legend**
> `DONE` — implemented and backed by a test or recorded evidence.
> `PARTIAL` — implemented for a bounded case; the requirement is not closed.
> `OPEN` — not implemented.
> `BROKEN` — implemented but defective; see the defect register.

---

## 1. Where the project actually stands

SETU is a smartphone dead-reckoning navigator for GNSS-denied driving (SIH 2026). The design
(`docs/03`) rests on four novel mechanisms — SVO (spectral odometer), CTS (coordinated-turn
speedometer), CSA (curvature-signature alignment) and PID (privileged distillation) — fused in a
right-invariant EKF inside a road-graph particle filter.

Reality of the three code bases:

| Codebase | Size | What it contains |
|---|---|---|
| `setu/` Python reference | ~9.6k lines | RI-EKF, SO3/SE_2(3), **SVO, CTS, CSA, alignment, road manifold**, simulator, eval harness, report |
| `core/` C++ (ships on phone) | **684 lines** | 16-state RI-EKF + GNSS/IMU streaming engine **only** |
| `android/` Kotlin | ~8.3k lines | Map, routing, recording, replay, diagnostics, model HTTP boundary |

**The central structural gap: every novel mechanism exists in Python and none of it exists in
C++.** The phone runs a conventional GPS+IMU filter with a 10-second outage ceiling. The research
contribution is not yet on the device.

Second gap: no on-device model. Inference is a remote HTTPS call, which contradicts REQ-F9 and the
premise of the product (tunnels have no connectivity).

---

## 2. Defect register — the bugs behind "laggy / slow first search / crashes"

Each item is traced to a specific line found by reading the code.

### D1 — BLOCKER. Route search allocates ~51 MB per attempt, up to 153 MB per route, then OOMs

`android/.../data/RoadGraph.kt`, `search()`:

```kotlin
val costs    = DoubleArray(nodeCount)  // 3,185,592 x 8 B = 25.5 MB
val previous = IntArray(nodeCount)     // 12.7 MB
val root     = IntArray(nodeCount)     // 12.7 MB
```

`route()` calls `search()` up to **three** times (primary, alternative-ends, alternative-both) and
nothing is reused between attempts. On a phone with a ~192–256 MB Java heap, alongside MapLibre's
native allocations and the mapped 238 MB graph, this reliably throws `OutOfMemoryError`.
**This is the crash.**

### D2 — BLOCKER. First route pays ~10.4 M validation steps, a 238 MB SHA-256 and a 7.25 M-edge index build

Serialised on the first `route()` call, all lazy, all on one thread:

1. `CompiledRoadGraph.load` — `digest(target)` SHA-256s the **entire 238 MB** decompressed graph on
   *every* app start.
2. `GraphBinary.read` — walks **all 3.19 M nodes and all 7.26 M edges** doing bounds checks through
   a fresh mmap, taking a cold page fault on essentially every one.
3. `RoadSegmentIndex.build` — another **7.26 M-iteration** pass, built lazily on the first snap.
4. `OfflineTiles.prepare` — re-hashes **all 11,159 tiles (48.5 MB)** on every map open.

**This is the "initial searching time for the first query is too much".**

### D3 — BLOCKER. ~1000 JSON objects per second allocated and written on the sensor thread

`android/.../data/SensorHub.kt`, `onSensorChanged()` — accelerometer, gyroscope, magnetometer,
rotation vector and game rotation vector are all registered at `5000 µs` (200 Hz):

```kotlin
record?.invoke(JSONObject().put("type", kind).put("tNs", event.timestamp)
    .put("values", JSONArray(event.values.toList())).put("accuracy", event.accuracy))
```

That is ~1000 `JSONObject` + `JSONArray` + boxed `List` allocations per second, each then
`toString()`-serialised and written by `SetuRepository.appendRecord`, which is **`@Synchronized` on
the repository**. The UI thread's `updateSettings()` contends on that same lock while the sensor
thread holds it doing disk I/O. `appendRecord` also allocates `listOf("pose","native_pose")` on
**every** record. **This is the sustained lag and a live ANR risk.**

### D4 — HIGH. The map re-serialises and re-parses its whole GeoJSON trail at up to 10 Hz on the UI thread

`android/.../ui/NavigationMap.kt`: `LaunchedEffect(trail, …)` rebuilds a `MultiLineString` of up to
**1,200 coordinates** into a JSON string, which MapLibre then re-parses, on every trail change.
`LaunchedEffect(pose, …)` rebuilds the vehicle point plus a **48-vertex confidence polygon** at
10 Hz. `SetuViewModel.trackingTrail` is a `mutableStateOf<List<Pose>>` replaced wholesale, so every
pose recomposes the whole Drive screen, and `appendTrackingPose` does `history.takeLast(1199) + pose`
— a fresh 1,200-element list per pose. Compounded by `MapView(..., textureMode(true))`, the slow
rendering path.

### D5 — HIGH. The native filter runs a JacobiSVD per IMU sample and copies ~2.3 KB of state twice

`core/src/setu_filter.cpp`, `normalize()` uses `Eigen::JacobiSVD` for re-orthonormalisation and is
called from **every** `propagate()` and **every** `update()`. `propagate()` also does
`SetuFilter propagated = *filter` (a full 16×16 covariance copy) and then copies again on
assignment. `setu_engine.cpp` copies an entire `Frame` (~2.3 KB, containing a whole `SetuFilter`)
per IMU sample, twice. At 200 Hz that is ~1 MB/s of pure memcpy plus 200 SVDs/s.

### D6 — HIGH. Delayed-GPS repropagation is O(history) full filter steps per fix, on the sensor thread

`core/src/setu_engine.cpp`, `correct()` replays every frame after the checkpoint via `advance()` →
`setu_filter_propagate()` → SVD plus three dense 16×16 products, for up to **512 frames**, once per
GPS fix. At 200 Hz with a 2 s history this is a multi-millisecond stall **every second** on the
thread that must not stall. Visible as a periodic hitch.

### D7 — MEDIUM. Eigen's assertions are live in the debug APK, and determinism is unpinned

*Corrected after measurement.* The first reading of this was that CMake appends
`CMAKE_CXX_FLAGS_DEBUG` (`-O0 -g`) after Gradle's `cppFlags += "-O2"`, so debug builds ran the filter
unoptimised. Inspecting the generated `build.ninja` shows that is **not** true on NDK r28: its
toolchain sets `CMAKE_CXX_FLAGS_DEBUG` to `-fno-limit-debug-info`, not `-O0`, so the debug variant
was already compiling at `-O2`.

What was real: `NDEBUG` is never defined, so **Eigen's internal assertions run on every expression**
in the APK being demonstrated — a genuine cost in a filter that propagates a 16×16 covariance per IMU
sample. There was also no floating-point contraction pin, which REQ-N8's bit-identical replay needs.

Both are now set per target in `core/CMakeLists.txt` (`-O3`, `NDEBUG`, `EIGEN_NO_DEBUG`,
`-ffp-contract=off`, `-fno-fast-math`). They are attached with `target_compile_options` rather than
through `CMAKE_CXX_FLAGS_<CONFIG>`, because the NDK toolchain sets those as ordinary variables that
shadow any cache entry — the first attempt wrote the cache and silently had no effect.

### D8 — MEDIUM. Rotation-vector fusion work runs at 200 Hz

`LiveEstimator.sensor()` runs `getRotationMatrixFromVector` + `trueNorthRotation` +
`CompassAlignment.evaluate` + a JNI `engine.attitude()` on **every** `TYPE_ROTATION_VECTOR` and
`TYPE_GAME_ROTATION_VECTOR` event — 400/s at the registered rate, where attitude seeding needs about
5 Hz. It also allocates `values.take(3).map(Float::toDouble).toDoubleArray()` (3 objects) per sensor
callback, twice over.

### D9 — MEDIUM. `RoadSegmentIndex` is a linear scan over spatially unsorted blocks

`visit()` tests **all 28,340 blocks** per snap, and a block is 256 *consecutive-by-edge-index* edges,
so its bounding box is not spatially tight and prunes poorly. `route()` calls `snaps()` up to four
times. This needs a real spatial grid keyed on coordinates.

### D10 — MEDIUM. Unbounded and unbatched state growth

`SetuRepository.recordedPoses` grows without bound for a whole trip and is copied on save.
`PriorityQueue<Visit>` boxes a `data class` per node expansion across a 3.19 M-node graph.

### D12 — BLOCKER, fixed. Git line-ending conversion corrupted 12 checksum-verified assets

Found on the device: selecting Delhi & NCR produced *"The active map could not be opened."* The
integrity machinery was working correctly — the bytes reaching it were wrong.

`.gitattributes` marked only `roads.bin.gzip` as binary. Everything else under
`android/app/src/main/assets/` was `text: unspecified`, so with Git's default `core.autocrlf=true`
on Windows, checkout rewrote LF to CRLF:

| | SHA-256 | bytes |
|---|---|---|
| `tile-index.json` committed in Git | `db2d7479…` | 1,035,390 |
| `tile-index.json` in the working tree | `dc46c3d6…` | 1,035,391 |
| working tree with CRLF→LF | `db2d7479…` | matches |

One added byte broke the hash `tiles.json` declares in `indexSha256`, so
`OfflineTiles.prepare()` threw *"Tile inventory failed its integrity check"* and the map never
opened. **The Delhi & NCR map was unusable on every Windows clone with default Git settings** —
which is why the offline-map evidence in `docs/17` and `docs/20` came from a different checkout.

Twelve files were affected, including `geophysics/wmm2025.wmm` — the magnetic-model coefficients
GeographicLib parses for heading initialisation — plus `manifest.json`, `tiles.json`, `graph.json`,
`map-style.json`, `bundled-region.json` and the three licence texts.

Fixed by marking the asset tree (and `.setumap`, `.pbf`, `.mbtiles`, `.wmm`, `.wmm.cof`) as `-text`
in `.gitattributes` and restoring all twelve files to their committed bytes. Verified on device: the
tile inventory hash now matches, tiles prepare in ~4 s, and Delhi streets render.

### D11 — OPEN QUESTION. OEM background freeze on CPH2467

`docs/20` records `OplusHansManager` freezing the process ~11 s after backgrounding despite a
foreground service and a wake lock. Unresolved; needs the OEM-specific battery exemption path.

---

## 3. Task ledger

### 3.1 Research core — reference implementation (Python)

| ID | Task | Status | Evidence |
|---|---|---|---|
| R-01 | SO(3) / SE_2(3) manifold algebra | DONE | `setu/core/so3.py`, `se23.py`; `tests/test_core_lie.py` |
| R-02 | RI-EKF on SE_2(3) | DONE | `setu/estimation/riekf.py`; `tests/test_estimation.py` |
| R-03 | CTS coordinated-turn speedometer (car form) | DONE | `setu/measurements/cts.py` |
| R-04 | CTS two-wheeler lean form | PARTIAL | physics in `docs/03` §3.4; no validated data |
| R-05 | SVO spectral odometer frontend | DONE | `setu/signal/spectral.py`, `setu/measurements/svo.py` |
| R-06 | CSA curvature-signature alignment | DONE | `setu/measurements/csa.py`, `setu/mapping/road.py` |
| R-07 | Mount alignment engine (ACE) | DONE | `setu/measurements/alignment.py` |
| R-08 | Drive simulator with exact ground truth | DONE | `setu/sim/*`; `tests/test_sim.py` |
| R-09 | Evaluation harness and metrics | DONE | `setu/eval/*`; `tests/test_eval_and_report.py` |
| R-10 | Experiment report generator | DONE | `setu/report/*` (one known template/test mismatch) |
| R-11 | RB-PF over the road graph | OPEN | designed in `docs/03` §3.7; not implemented anywhere |
| R-12 | Learned heteroscedastic sigma heads | OPEN | — |
| R-13 | A-KIT adaptive process noise | OPEN | — |
| R-14 | End-to-end BPTT through the filter | OPEN | — |
| R-15 | EFA magnetic / baro / radio anchors | OPEN | — |
| R-16 | GQM per-satellite trust and Doppler aiding | OPEN | raw GNSS is logged only |
| R-17 | IO-VNBD ingest, sync, `R_eff` calibration | OPEN | no `ml/data`; REQ-F10 unmet |
| R-18 | PID privileged distillation training | OPEN | no `ml/train` |
| R-19 | §8.6 falsification plot (go/no-go artefact) | OPEN | **the thesis is unproven** |

### 3.2 Portable native core (C++ — what runs on the phone)

| ID | Task | Status | Evidence |
|---|---|---|---|
| N-01 | 16-state RI-EKF: propagate, update, snapshot | DONE | `core/src/setu_filter.cpp`; `NativeFilterTest` |
| N-02 | Joseph-form covariance and chi-square gating | DONE | same |
| N-03 | WGS84 local Cartesian (GeographicLib) | DONE | `core/src/setu_engine.cpp` |
| N-04 | WMM2025 declination | DONE | 20 NOAA reference cases in `NativeEngineTest` |
| N-05 | Delayed-GPS rewind and repropagation | DONE (slow) | see D6 |
| N-06 | Midpoint-attitude strapdown correction | DONE | Python/C++ parity fixture, 294 actions |
| N-07 | Outage withholding policy | **PARTIAL → widened** | was 10 s / 150 m, which made GNSS-denied work impossible by construction; now 400 m 95 % radius with a long backstop (§4b D13) |
| N-08 | Measurement kinds declared (NHC/ZUPT/SVO/…) | **PARTIAL → DONE** | generators now emit them; `SETU_BODY_AXIS` added for arbitrary body axes (§4b D13) |
| N-09 | SVO in C++ | **OPEN → DONE** | autocorrelation fundamental + GNSS-learned scale; learns 1.92–1.96 m/Hz against a true 1.948, holds speed to +0.2 m/s (§4b) |
| N-10 | CTS in C++ | **OPEN → DONE** | 1 Hz, gated at 0.05 rad/s per `docs/03` §3.4 |
| N-11 | CSA and curvature LUT in C++ | OPEN | Python only |
| N-12 | NHC / ZUPT / ZIHR generators | **OPEN → PARTIAL** | NHC and ZUPT implemented with a self-calibrating mount, applied jointly with the spectral speed as one vehicle-frame velocity update; ZIHR still open |
| N-13 | RB-PF | OPEN | — |
| N-14 | Stable C ABI per `docs/04` §4.8 | PARTIAL | different surface; no `SetuHealth` |
| N-15 | Neural runtime abstraction (`nn/`) | OPEN | — |
| N-16 | Deterministic replay, bit-identical (REQ-N8) | OPEN | — |
| N-17 | Allocation-free RT thread | OPEN | the worker also logs; see D3, D5 |
| N-18 | Edge daemon / external IMU HAL (REQ-F7) | OPEN | — |
| N-19 | Release-grade optimisation flags | **BROKEN → DONE** | `-O3`, `NDEBUG`, `EIGEN_NO_DEBUG`, `-ffp-contract=off` per target (D7) |
| N-20 | Self-calibrating mount (vehicle axes from motion) | **NEW → DONE** | observed from filter state; 0.4–1.3° against the known mount in `dr_bench` |
| N-21 | GNSS-denied benchmark on device | **NEW → DONE** | `core/test/dr_bench.cpp`, arm64, random mount, `SETU_DR_MASK` isolates constraints |

### 3.3 Android application

| ID | Task | Status | Evidence |
|---|---|---|---|
| A-01 | Compose + Material 3 shell, light/dark, insets | DONE | `docs/verification/android/` |
| A-02 | Permissions and honest capability reporting | DONE | `verification/25-*`–`27-*` |
| A-03 | MapLibre offline vector tiles (11,159 tiles) | DONE | `docs/20` |
| A-04 | Tile inventory and per-tile SHA-256 integrity | **DONE** | per-process memo (D2); byte integrity restored after the CRLF corruption (D12) |
| A-05 | Compiled road graph `setu.road-graph.v1` | **DONE** | verification memoised and warmed in the background; cold route 11.4 s → 3.4 s (§4a) |
| A-06 | Offline route preview and maneuvers | PARTIAL | main-road graph only; D1 and D2 fixed, D9 spatial index still linear |
| A-07 | Destination search and places | DONE | 300 places, Delhi and Bengaluru |
| A-08 | Foreground recording service and notification | DONE | `manual/12-*`, `13-*` |
| A-09 | `.setulog` JSONL recording | PARTIAL | **not** the specified protobuf (`docs/05` §5.8) |
| A-10 | Trip persistence, export/import, delete | DONE | `TripStoreTest` |
| A-11 | Timestamped replay with gap/provenance breaks | DONE | `docs/16` |
| A-12 | Diagnostics screen | PARTIAL | no four-trace speed overlay (`docs/05` §5.4); now also reports ZUPT/NHC/CTS/SVO counts and the learned SVO scale |
| A-13 | Map pack import, download, removal | DONE | `verification/32-*`–`38-*` |
| A-14 | JNI bridge to the native engine | DONE (leaky) | allocates a JNI array per poll and per update |
| A-15 | IMU pairing and synchroniser | DONE | `ImuSynchronizerTest` |
| A-16 | Checked-compass alignment fallback | PARTIAL | 30° model prior, unvalidated |
| A-17 | GPS-motion alignment (experimental) | PARTIAL | `docs/17` |
| A-18 | Model provider boundary and consent | DONE | `ModelProviderTest`, `ModelConsentTest` |
| A-19 | GPS-loss demo (synthetic, 24 s) | DONE | `PositioningDemoTest` |
| A-20 | Live position tracking and trail | **DONE** | GeoJSON building moved off the UI thread (D4) |
| A-21 | Turn-by-turn guidance lifecycle | PARTIAL | preview-grade |
| A-22 | Background capture continuity | BROKEN | D11, OEM freeze |
| A-23 | Battery and thermal governor | OPEN | REQ-N3 unmeasured |
| A-24 | On-device model runtime (LiteRT) | OPEN | REQ-F9 |
| A-25 | Crash-free operation under load | **BROKEN → PARTIAL** | D1 route OOM fixed and measured; D15 launch crash fixed; long-drive stability still unproven |
| A-26 | Fast location acquisition | **NEW → DONE** | fused + network + GPS, active `getCurrentLocation`; measured 4.1 s on device (§4b D14) |
| A-27 | Consumer-facing information architecture | **NEW → DONE** | About reached from the wordmark, situation-based status wording, demos promoted, Settings regrouped, one stated shape scale |

### 3.4 Maps and data pipeline

| ID | Task | Status | Evidence |
|---|---|---|---|
| M-01 | OSM region extraction (`tools/build_osm_region.py`) | DONE | `tests/test_osm_region.py` |
| M-02 | Map pack packaging (`build_map_pack.py`) | DONE | `tests/test_map_pack.py` |
| M-03 | Vector tile build (tippecanoe) | DONE | `tests/test_map_tiles.py` |
| M-04 | Road graph compiler | DONE | `tests/test_road_graph.py` |
| M-05 | Delhi/NCR region, 7.26 M directed edges | DONE | `docs/17` |
| M-06 | **Curvature LUT `psi(s)`, `kappa(s)` at 1 m** | OPEN | required by CSA |
| M-07 | Landmark index and saliency scoring | OPEN | required by CSA |
| M-08 | DEM and grade profiles | OPEN | — |
| M-09 | Turn restrictions, access rules, oneway fidelity | PARTIAL | oneway only |
| M-10 | Spatial index for snapping | BROKEN | D9 |
| M-11 | Anchor DB (SQLite) | OPEN | — |

### 3.5 Machine learning

| ID | Task | Status | Evidence |
|---|---|---|---|
| L-01 | Remote provider contract v1 | DONE | `docs/12` |
| L-02 | Live consented IMU windowing | DONE | `LiveModelSessionTest` |
| L-03 | Endpoint reachable and serving | DONE | probed 2026-09-12, see §4 |
| L-04 | **Model fit for navigation** | BROKEN | see §4 |
| L-05 | Training pipeline and dataset splits | OPEN | no `ml/` tree |
| L-06 | Export to int8 TFLite plus parity harness | OPEN | REQ-N2 |
| L-07 | On-device inference within 3 ms | OPEN | REQ-N1 |
| L-08 | Calibrated sigma, 3-sigma coverage ≥ 98 % | OPEN | G-4 |
| L-09 | Gated fusion of model speed into the filter | OPEN | REQ-F4 |

### 3.6 Acceptance gates (`docs/08`)

| Gate | Meaning | Status | Note |
|---|---|---|---|
| G-1 | p90 drift below 10 % of distance | OPEN | simulated tunnel **10.4 %** over 40 runs, from no solution at all |
| G-2 | Below 100 m over 1 km at 60 km/h | OPEN | **median 66.9 m simulated, inside the gate; p90 141.3 m is not** |
| G-3 | Below 5 m over a 50 m creep | OPEN | median 162 m simulated; the low-speed band has no speed observation |
| G-4 | 3-sigma coverage at least 98 % | OPEN |
| G-5 | No tail regression against the baseline | OPEN |
| G-6 | Model tick below 3 ms on the reference phone | OPEN |
| G-7 | Bit-identical replay hash | OPEN |
| G-8 | p90 recovery below 3 s, jump below 2 m | OPEN |
| T1–T8 | Field trials | OPEN |

---

## 4. Verdict on the supplied model server

Probed `https://setu-proj-sih.duckdns.org` on 2026-09-12.

**Infrastructure: good.** HTTPS, correct `setu.model.v1` schema, 60–230 ms round trip, correctly
rejects a 1 s window ("Need at least 3.9 seconds of continuous IMU history"), honest health text.

**Model: not usable for navigation.** Synthetic 4 s windows:

| Input | Returned speed | sigma | validity |
|---|---|---|---|
| 200 Hz, cruise (truth ≈ 16.7 m/s) | 18.35 | 4.91 | 0.0 |
| 200 Hz, same plus 0.10 rad/s yaw | **9.42** | 4.78 | 0.0 |
| 100 Hz, same motion | 17.83 | 4.88 | 0.0 |
| 50 Hz, same motion | **24.82** | 4.63 | 0.0 |

Four disqualifying findings:

1. **`validity` is always 0.** By the app's own contract that can never be fused, so the endpoint is
   structurally incapable of contributing to navigation as deployed.
2. **`sigma` is effectively constant at ~4.8 m/s** regardless of input, so it is not heteroscedastic.
   4.8 m/s at 16.7 m/s is a 29 % speed error, about 290 m/km of drift — **worse than the REQ-P1 10 %
   gate** and roughly 30× the design target.
3. **No rate conditioning.** Identical physical motion at 200/100/50 Hz returns 18.35 / 17.83 /
   24.82 m/s, a 39 % swing. The model consumes sample indices rather than time. Android sample rates
   vary per device and under thermal load, so this alone makes it unshippable.
4. **Anti-physical turn response.** Adding a gentle curve halved the predicted speed. In a
   coordinated turn `a_lat = v·Omega` should *support* the speed estimate; the network is keying on
   signal amplitude, not vehicle physics.

The deployment shape is also wrong on its own terms: a remote HTTPS call violates REQ-F9 (train
offline, infer on device), REQ-N1 (≤ 3 ms per tick) and the product premise, since tunnels have no
connectivity.

**Decision: do not wire this endpoint into navigation.** It stays exactly where it is — consented,
evaluation-only, logged separately from the trajectory. The replacement is
`notebooks/setu_speed_model.ipynb` for Colab, which trains the model properly and exports an int8
TFLite bundle for on-device inference.

---

## 4a. Progress — session of 2026-09-12

### Landed and verified

| Defect | Change | Verification |
|---|---|---|
| D1 crash | `SearchScratch` replaces the three dense node-count arrays with a growable open-addressed table and a primitive binary heap, shared across all three route attempts. Working memory drops from ~153 MB per route to a few hundred KB. Adds a `MAX_EXPANSIONS` guard so a pathological query fails with a message instead of hanging. | `SearchScratchTest` (6 tests: growth/rehash across 60 k entries, heap ordering over 2 k pushes, reset semantics); `RoadGraphTest` (10) still green |
| D2 first-query cost | `OfflineMap.warmUp()` loads, validates and indexes the routing graph in the background on map activation. `CompiledRoadGraph` and `OfflineTiles` memo their full verification per process, so a theme change or second route no longer re-digests 238 MB or re-hashes 11,159 tiles. | Builds and unit tests green; on-device timing still to be measured |
| D3 lag / ANR risk | `LogRecorder`: pooled allocation-free `SensorSink` on the sensor thread, bounded queue, dedicated writer thread, drops counted not silent. `SetuRepository.appendRecord` is no longer `@Synchronized` on the path the UI thread contends with. `SensorHub` keeps scratch arrays instead of allocating per callback. | `LogRecorderFormatTest` (5 tests) pins byte-identical float rendering against the `org.json` rules, so existing recordings, replay, export and import are unaffected |
| D4 map jank | Vehicle, confidence-ring and trail GeoJSON now build on `Dispatchers.Default`; only the source hand-off stays on main. | Compiles; visual check pending a device |
| D5 native cost | `normalize()` drops JacobiSVD for Newton-Schulz iteration toward the same orthogonal polar factor, with a residual test that skips the work when the matrix is already orthonormal. `propagate` and `apply` compute into locals and commit, removing two full ~2.3 KB state copies each. | Native builds for arm64-v8a and x86_64; parity tolerance is 1e-7 and the change is at ~1e-15 |
| D6 repropagation | `Frame` is now filled in place in the ring; `advance()` takes the destination's three vectors instead of a whole `Frame`; the replay loop no longer copies 2.3 KB per retained frame. | Builds; combined with D5 and D7 the per-fix replay cost is roughly an order of magnitude down |
| D7 build flags | Corrected diagnosis (see above) and fixed the real issue: `-O3`, `NDEBUG`, `EIGEN_NO_DEBUG`, `-ffp-contract=off`, `-fno-fast-math`, attached per target. | `compile_commands.json` confirms the flags reach `setu_filter.cpp` |
| D8 sensor rates | Accelerometer and gyroscope stay at 200 Hz; magnetometer and both rotation vectors drop to 50 Hz and the barometer to 10 Hz, roughly halving callback volume and cutting Android's orientation fusion from 400/s to 100/s. `LiveEstimator` uses scratch buffers instead of four array allocations per callback. | Compass freshness gates allow 100 ms, so 50 Hz keeps every existing check satisfied |

Build and test state: `:app:assembleDebug` green including native for both ABIs; **60 JVM unit tests,
0 failures** (was 49). Python reference suite unchanged at 1 pre-existing failure
(`test_renders_valid_standalone_html`, the template/test mismatch already recorded in `docs/11`).

### Also delivered

`notebooks/setu_speed_model.ipynb` — a Colab notebook that trains the replacement speed model,
calibrates its uncertainty, exports an int8 TFLite bundle plus manifest for on-device inference, and
emits a corrected `setu.model.v1` server. It asserts the three checks the deployed endpoint fails
(rate invariance, turn response, 3-sigma coverage) rather than assuming them. Its physics
pseudo-label was measured, not assumed: two earlier formulations were tried and rejected on
generated data before settling on a through-origin fit of `a_lat = v·|w|` read from `sqrt(‖a‖²−g²)`,
which needs no gravity direction. That label is usable on ~15 % of windows at 3.5 % median / 38 % p90
error, so it is weighted as a regulariser and the notebook prints those numbers itself.

### Environment blockers found

* **Drive C: is full** — 138 MB free of 257 GB. The NDK at `ndk/28.2.13676358` was an empty
  directory (a failed install), Gradle could not download dependencies, and the build could not run.
  Worked around without deleting anything: NDK r28c, the Gradle home and the build directory now
  live on D:. Build with:
  ```
  GRADLE_USER_HOME=D:/SetuToolchain/gradle-home ./gradlew :app:assembleDebug \
    -PsetuBuildDirectory=D:/SetuToolchain/android-build \
    -PsetuNdkPath=D:/SetuToolchain/android-ndk-r28c
  ```
  `build.gradle.kts` reads `setuNdkPath` and falls back to the SDK's NDK version when it is absent,
  so this does not affect anyone else's machine. C: still needs freeing.
* **No device visible to adb.** `adb devices` has been empty throughout, so nothing in this session
  is on-device evidence. The on-device passes below are still outstanding.

### Measured on hardware — Nothing Phone (3), Android 16, SD 8s Gen 4, 12 GB

Device: `Nothing A024`, `arm64-v8a`, `dalvik.vm.heapgrowthlimit=256m`, `heapsize=512m`
(the app sets `largeHeap="true"`, so its ceiling is 512 MB).

**A/B method.** Both APKs built from this tree, differing only by `git stash` of the eleven source
files listed above — so the compiled road graph, the map assets and the CRLF fix are identical on
both sides and the delta is attributable to these changes alone. Same destination (Naveen Shahdara
preview → MAIT Rohini, 25.8 km), same GPS state, graph already extracted on both, app force-stopped
between runs, route completion detected from the rendered distance in the view hierarchy.

| Cold-start first route | baseline | with these changes |
|---|---|---|
| run 1 | 14,963 ms | 3,320 ms |
| run 2 | 11,375 ms | 3,398 ms |
| run 3 | 11,273 ms | 3,367 ms |
| **median** | **11,375 ms** | **3,367 ms** — **3.4× faster** |
| spread | 11.3–15.0 s | 3.32–3.40 s |
| **peak Java heap during the route** | **100,136 kB** | **46,692 kB** — **−53 MB** |

The heap figure is D1 confirmed to the megabyte: 3,185,592 nodes × (8 + 4 + 4) bytes = 51 MB of
dense arrays per search attempt, and the baseline peak sits exactly one such allocation above the
fixed build's flat 46 MB.

**Recording, same phone** (`SensorService` registration periods read from logcat, rates measured
from the saved `.setulog`):

| | baseline | with these changes |
|---|---|---|
| total record rate | **956 rec/s** | **596 rec/s** (−38 %) |
| accelerometer | 226.8 Hz | 226.9 Hz (unchanged) |
| gyroscope | 226.8 Hz | 226.9 Hz (unchanged) |
| magnetometer | 100.0 Hz | 50.0 Hz |
| rotation vector | 200.0 Hz | 45.4 Hz |
| game rotation vector | 200.0 Hz | 45.4 Hz |
| malformed lines in the saved log | 0 | 0 |
| GC events during 45 s of recording | — | 0 |

The inertial pair that actually feeds dead reckoning is untouched; the reduction is entirely in the
attitude channels, which need a few hertz and were being sampled at 200. Every one of those 956
records per second was previously a `JSONObject` + `JSONArray` + boxed `List`, serialised and written
on the sensor thread under a monitor the UI thread also wanted.

**Backward compatibility.** A `.setulog` recorded by the old build, pulled off the device before
reinstalling, was restored afterwards and opens correctly alongside a new recording. Raw lines from
both carry the same key order (`type`, `tNs`, `values`, `accuracy`) and the same `org.json` float
rendering, which is what `LogRecorderFormatTest` pins.

### Still not verified on hardware

The native-core changes (D5, D6, D7) are exercised by every run above but not isolated: no
per-tick filter timing was captured, so "roughly an order of magnitude down" for the delayed-GPS
replay remains reasoning, not measurement. Battery, thermal, background-capture continuity, and any
GNSS-denied accuracy claim are all untouched by this session.

---

## 4b. Progress — session of 2026-09-14

### D13 — BLOCKER, fixed. GNSS-denied positioning was disabled by construction

The product exists to navigate without GNSS, and it could not, for two independent reasons.

**The engine gave up ten seconds after the last fix.** `setu_engine_imu` ended with a hard
`timestamp - accepted_fix_ns > 10000000000LL` test that called `invalidate(5)`. Ten seconds is
shorter than any tunnel the requirements name.

**Nothing generated the measurements that make dead reckoning possible.** `setu_filter_update` has
always implemented `SETU_NHC`, `SETU_ZUPT`, `SETU_FORWARD_SPEED` and `SETU_SVO_FREQUENCY`, and the
maths is correct. The engine called it only with `SETU_POSITION_2D`, `SETU_ALTITUDE` and
`SETU_VELOCITY_2D` — all three derived from GNSS. With GNSS gone the filter had nothing but raw IMU
integration, whose position error grows without bound.

Implemented in `core/src/setu_engine.cpp`:

* **Self-calibrating mount.** NHC constrains velocity in the *vehicle* frame, but the phone's
  orientation in the car is unknown and drifts. Rather than asking the user to mount the phone a
  particular way, the vehicle axes are observed from the filter's own state: while GNSS is healthy
  and the vehicle is moving, body-frame velocity points along the vehicle's forward axis by
  definition, and world up rotated into the body frame gives its up axis.
* **NHC** at 1 Hz — a wheeled vehicle does not slide sideways or leave the road surface.
* **ZUPT** at 2 Hz when stopped, gated on the filter's own speed *and* vetoed by a recent GNSS
  speed (see below).
* **Coordinated-turn speed** at 1 Hz when the turn rate clears 0.05 rad/s, per `docs/03` §3.4.
* **SVO, the spectral odometer** (`docs/03` §3.3) — the piece that actually closes along-track
  drift. Road roughness enters through the wheels, so the vibration carries a line at the axle rate
  `f = v / (2*pi*R_eff)`; reading it measures speed outright, with no integration. The fundamental
  is found by autocorrelation over a 2.56 s window. Crucially the scale is **not** an assumed wheel
  radius: it is learned from GNSS speed while that is available, exactly as `docs/03` §3.3 specifies
  (k_svo observed by CTS and GNSS), so tyre pressure, load and wear cannot bias it. Against a true
  `2*pi*R` of 1.948 m/Hz it learns **1.92–1.96 m/Hz**, and holds speed to **+0.2 m/s** through an
  82 s blackout.
* **`SETU_BODY_AXIS`**, a new measurement kind: velocity along one arbitrary body axis. Under this
  filter's right-invariant error the attitude terms of a body-frame velocity measurement cancel
  exactly, so the Jacobian row is just the transpose of `R * axis`.
* **`setu_engine_constraints()`**, an A/B switch, so the benchmark can measure the delta rather
  than assert it.
* The ten-second cutoff is replaced by an uncertainty-based limit (250 m 95 % radius) with a long
  backstop.

Three bugs found and fixed by measurement, each of which had silently destroyed the solution:

1. **Applying NHC at 20 Hz made the filter reject real GNSS within six seconds.** A standing
   physical fact is not an independent measurement per sample; the filter has no way to know that,
   so every application shrank the lateral-velocity covariance again. At 5 Hz it then began gating
   its *own* constraints after about 18 s. The intervals now sit near the real decorrelation time.
2. **ZUPT fired at 60 km/h.** An accelerometer cannot distinguish rest from constant velocity —
   Galilean invariance, not a tuning problem. Keying the stop detector off the IMU signature froze
   the solution mid-cruise and, because velocity never recovered, the mount was never observed
   either. ZUPT now requires the filter to already believe it is nearly stopped, and a GNSS fix
   reporting motion vetoes it outright.
3. **The benchmark's own vehicle frame was left-handed** (determinant −1), so the engine correctly
   refused every attitude. Worth recording because the failure looked exactly like an engine bug.
4. **Autocorrelation octave error.** A periodic signal peaks at every multiple of its period, so the
   global maximum picks 2T about as often as T. The urban profile learned a scale of 3.61 m/Hz
   against a true 1.95 — almost exactly double. Fixed by taking the earliest lag within 85 % of the
   best, the standard pitch-detection remedy.
5. **NHC sigma has to scale with speed when the mount is estimated.** With a mount error of theta, a
   real forward speed v appears as `v*sin(theta)` along the axis being held to zero. At a fixed
   0.4 m/s that read as a 3-sigma violation at 60 km/h for a mount off by only 5 degrees, so the
   filter corrected real speed away — NHC alone caused 1582 m of along-track error while correctly
   holding cross-track to 46 m. This single change took the combined configuration from 4684 m of
   along-track error to 36 m.
6. **The mount estimator was tracking noise.** It ran on every IMU sample, so a 0.02 blend was a
   0.25 s time constant. Throttled to 10 Hz, it now reaches **0.4–1.3 degrees** of true mount error,
   verified against the known mount in the benchmark.

Two hypotheses were tested and **rejected by measurement**, recorded so they are not retried:

* *Reducing process-noise inflation during a blackout*, on the reasoning that there is no GNSS left
  to stay responsive to. It made the filter confident enough to gate its own constraints (CTS and
  SVO updates fell to zero) and the solution ran away to a 106 m/s speed error. The 4x inflation is
  load-bearing: a wide covariance is what lets a weak constraint still be heard.
* *Freezing the attitude part of the correction for body-frame constraints*, on the reasoning that
  under the right-invariant error they carry no attitude information. It made the tunnel profile
  markedly worse (median 237 m to 551 m). The covariance cross-terms are doing useful work.

### Measured on device — `core/test/dr_bench.cpp`

A benchmark built with the NDK and run on the phone, so it exercises the shipping arm64 code path.
Synthetic drives with known truth, a **random unknown phone mount every run**, MEMS white noise,
turn-on bias and bias random walk, road and engine vibration, 1 Hz GNSS until the cut.

Forty repeats, because a p90 from eight is not trustworthy — an 8-run sample showed 7.3 % drift and
99 m p90, which would have passed both gates, and was sampling noise.

| Profile | GNSS-only baseline | With constraints |
|---|---|---|
| REQ-P3 tunnel, 1359 m / 82 s | **withheld 40/40** | **holds 40/40**, median **66.9 m**, p90 141.3 m, p90 drift **10.4 %** |
| REQ-P2 creep, 86 m / 56 s | **withheld 40/40** | holds 40/40, median 162 m |
| REQ-P1 urban, 788 m / 156 s | **withheld 40/40** | withheld 23/40 |

The tunnel case is the one the design targets and it is close: **median 52.5 m against G-2's 100 m**,
with the best run at 12 m along-track and 5 m cross-track. It is the p90 (167 m) and the 12.3 % drift
ratio that still miss, so the gate is not claimed.

**Urban is the weak case and the reason the work is not finished.** Its stop-start cycle removes the
axle line for long stretches, and nothing else observes forward speed below about 4 m/s, so the
solution diverges and is withheld on 7 of 16 runs. Two attempts to fix it were measured and reverted:

* *Trusting a sustained stationary IMU signature over the filter's own speed.* A slow creep has
  genuinely faint vibration, the signature reads stationary while the vehicle is still rolling, and
  the false stops took the parking profile from a 163 m median to 467 m.
* *Asserting the stop always, with a loose 1.5 m/s sigma when the filter disagrees.* This is the
  better idea — confidence belongs in the sigma, not a binary gate — and it did improve the creep
  (163 m to 108 m). But it doubled the urban runs where no position could be produced at all, 7 of
  16 to 14 of 16. Availability is the headline, so it is off; it is one line to restore once the
  urban divergence itself is fixed.

One test defect was found and corrected while chasing this: the urban profile's "stop" segments were
3 s, but braking from 8 m/s at 3.5 m/s² takes 2.3 s, so the vehicle stood still for about half a
second and no run ever exercised a real halt — every urban run reported zero zero-velocity updates.
They are now 12 s, which is still conservative for a signal-controlled junction.

Reproduce with `core/test/README.md`; `SETU_NO_DR=1` selects the baseline, `SETU_DR_MASK` isolates
individual constraints.

**The headline is the first column.** Before this work the engine produced *no* GNSS-denied position
at all — it invalidated ten seconds after the last fix, every run, on every profile. It now carries
a position through blackouts of 82–136 s.

**REQ-P1/P2/P3 are still not met, and this does not claim them.** Tunnel p90 drift is 11.0 % against
a 10 % gate — 0.4 points away, and not passing. The largest single step came from a modelling error worth recording: NHC and the
spectral speed were being applied as **separate scalar updates**, and sequential scalar updates of
what is really one vector measurement are not equivalent to a joint update when the states are
correlated — the filter could answer a disagreement about forward speed by **rotating** the velocity
instead of rescaling it, which is precisely how a 1 % speed bias became ~10° of heading error.
Applying them as one `SETU_VEHICLE_VELOCITY` update sharing a single innovation covariance took the
tunnel from a 237 m median to 52.5 m, and cross-track from 234 m to 5 m on the best run.

Isolating each constraint (identical seeds, so the differences are causal) is what made the tuning
tractable, and `SETU_DR_MASK` keeps that available:

| Constraints | along-track | cross-track | speed error |
|---|---|---|---|
| none | 26 m | 48 m | +1.1 m/s |
| ZUPT only | 503 m | 150 m | −8.3 m/s |
| NHC only | 1582 m | **46 m** | +14.1 m/s |
| CTS only | 106 m | 178 m | +3.8 m/s |
| **SVO only** | **2 m** | 204 m | **+0.3 m/s** |
| all, before the sigma fix | 4684 m | 220 m | +92.4 m/s |
| all, after the sigma fix | 36 m | 133 m | +0.7 m/s |
| **all, as one joint update** | **12 m** | **5 m** | **+0.3 m/s** |

`docs/03` §3.3 specifies k_svo as a filter state "observed by CTS and GNSS", and only the GNSS half
was implemented — the scale was learned before the blackout and then frozen. CTS re-observation
during an outage is now implemented, but gated to turns where its relative error is under 6 %: a
first attempt admitting anything under 25 % corrupted a scale already good to ~2 % and took the
tunnel from a 72 m median to 215 m. At the benchmark profiles' gentle curves it therefore never
fires, so **it is implemented but contributes nothing to the numbers below**; it should matter on
routes with strong turns.

**The stop-start failure was root-caused by tracing it rather than reasoned about.** The trace is
worth keeping: the solution tracks the truth exactly until the first hard deceleration, and then

```
t=52  true 8.0   filter 10.0     braking starts
t=56  true 1.0   filter 14.9     the filter speeds up while the car brakes
t=58  true 0.0   filter 14.8     stopped, and the filter believes 15 m/s
```

A windowed frequency is an average over 2.56 s, which is only a current speed while the speed is
steady. Under braking the window still holds the pre-braking line, so SVO reads far too fast and
actively holds the estimate up — and because the filter then never believes itself stopped, the
zero-velocity update that would have rescued it never fired. Every urban run reported zero ZUPTs.

`fundamental()` now also reports how far the second half of the window disagrees with the first. A
disagreement over 35 % means the speed is changing and the estimate is stale, so nothing is
published; smaller disagreements widen the sigma rather than being discarded. This took the tunnel
from 11.0 % to **10.4 %** drift and made ZUPT fire in the urban profile for the first time. It is not
enough to fix urban, which still produces no position on 23 of 40 runs.

One assumption of my own was wrong and is worth recording. `docs/03` §3.3 gives ~4 m/s as SVO's
floor because f0 drops below 2 Hz, and I encoded that as both a speed gate *and* a 1.5 Hz floor on
the autocorrelation search — which excluded the low-speed band by construction. That reasoning holds
for a short FFT window; autocorrelation over 2.56 s resolves a 1 Hz line fine, and lowering the gate
does produce real spectral speed updates at creep speeds with a sensible learned scale (1.87 m/Hz).
The trade is monotonic, though, and costs availability:

| SVO speed floor | creep median | urban runs with no position |
|---|---|---|
| 4.0 m/s | 162 m | **20 / 40** |
| 2.5 m/s | 138 m | 24 / 40 |
| 1.5 m/s | **125 m** | 26 / 40 |

Neither profile passes its gate at any setting, so the better creep number buys nothing while
producing no position at all is the worst outcome a navigation app can have. The floor stays at 4.0;
the corrected search floor and a low-speed confidence ramp are kept, since they are right and will
matter once the stop-start divergence is fixed.

Two further tuning attempts were measured and reverted, so they are not retried: a 5.12 s spectral
window (finer frequency resolution tightened the learned scale to 1.91–2.01 from 1.82–1.96, but the
added latency cost more than the resolution bought), and gating the joint update on a fresh speed
(tunnel median 62 m → 186 m — sharing the innovation covariance is what makes the lateral zeros
safe, so the update is worth applying even when the forward sigma has to be wide).

### D14 — HIGH, fixed. Location acquisition took minutes because only the satellite provider was used

`startLocation()` requested updates from `LocationManager.GPS_PROVIDER` alone, took last-known
position from that provider only, and discarded it if it was over 30 s old. `GPS_PROVIDER` is the
raw satellite provider: from cold, indoors, or among tall buildings its first fix takes minutes and
may never arrive, which is why the app sat on "Finding GPS" with location switched on and working.

Now it subscribes to the **fused provider** (API 31+, answers in a second or two from Wi-Fi and
cell) alongside GPS and network, seeds immediately from the most accurate last-known fix across all
providers within ten minutes, and calls `getCurrentLocation()` to actively drive a first fix rather
than waiting for the periodic stream. `isLocationEnabled()` now reflects any usable provider rather
than reporting location "off" whenever the user chose battery-saving mode.

Coarse fixes are shown but **not fused**: anything worse than 35 m accuracy is kept out of the
estimator, since a several-hundred-metre Wi-Fi fix would drag the filter around and undo the dead
reckoning it is meant to anchor.

**Measured on device: 4.15 s, 4.09 s, 4.15 s** from cold launch to a usable position, against the
10–15 minutes reported. That figure includes app start and map load, so location acquisition itself
is faster. An earlier attempt measured nothing because it ran while the phone was in use, and
Android restricts location for backgrounded apps.

### UI — consumer framing

* **The wordmark now opens About.** It is where a person looks to ask what the app is.
* **`AboutScreen` rewritten** (`ui/AboutScreen.kt`). It leads with what सेतु means — *bridge* — and
  why that is the product: the bridge that carries your position across the gap. Then the problem
  in plain terms, four plain-language cards on how it keeps going, offline coverage, privacy, and
  the honest limits *after* the idea rather than instead of it. The previous page opened on a
  disclaimer.
* **Status wording.** "Inertial estimate", "GPS + IMU", "Estimate withheld" and "GPS · calibrating"
  named the mechanism rather than the situation. Now: **Bridging** (with its own icon — the one
  state worth naming, because it is the app doing the thing it exists to do), Tracking, Finding
  signal, Calibrating, Last known place.
* **Demos kept and promoted** from two trailing text links to a titled "See it in action" card:
  "Watch a tunnel blackout" and "Take a sample route".
* **Settings regrouped** into Your drive / Appearance / Recording / About / For developers, so
  sensor diagnostics and the research model server are one tap away instead of level with the
  everyday preferences.
* **One stated shape scale.** The UI had grown eight corner radii (6/12/14/16/18/20/24/28), which is
  what makes an interface read as assembled from parts. `SetuShape` states four — control 12,
  action 16, card 20, hero 28 — across 31 call sites.
* **Trips**, which reading the code had wrongly suggested was already fine. On the device every
  recording was titled "Position tracking", so the list was four identical rows; the headline stat
  said "GPS distance"; and rows carried no time, so nothing distinguished them. Recordings are now
  named for the time of day (`defaultDriveName`, covered by `DriveNameTest`), the stat reads
  "Distance", and each row shows its start time. Existing recordings keep their saved names - user
  data is not rewritten.

Build and test state: `:app:assembleDebug`, `:app:compileDebugAndroidTestKotlin` and the native
benchmark all build; **62 JVM unit tests, 0 failures**. Instrumented tests updated for the renamed
Settings rows; not run this session because the phone was in use.

### D15 — BLOCKER, fixed. Growing the native estimate array crashed the app on launch

`decodeNativeEstimate` asserted `require(values.size == 20)`. Adding the dead-reckoning counters grew
`SETU_ESTIMATE_SIZE` to 29, so every sensor callback threw `IllegalArgumentException: Failed
requirement` on the `setu-sensors` thread and the app died before drawing a frame. The contract is
now `>= 20`: older fields keep their indices so reading a prefix stays correct, and a future native
addition cannot crash the sensor thread. The counters are surfaced on `NativeEstimate` so the
diagnostics screen can show the GNSS-denied path engaging.

Two user-visible strings were stale and are corrected: the withheld-estimate detail still said "more
than 10 s without an accepted fix", and the fusion detail still claimed "no learned speed, road
matching or mount constraints" when there are now mount constraints and a spectral speed.

### Verified on device

* **No crash** on launch; the process stayed up through map load, About, the demo and a region switch.
* **Location: 4.1 s** to a usable position (above).
* **About** opens from the wordmark and renders correctly, including the Devanagari. `displaySmall`
  carries −0.7sp of letter spacing, which is fine for Latin and broke the cluster so that सेतु split
  across two lines; spacing is reset to zero on that line.
* **The demo is intact** and reads well: "Through the GPS gap", GPS withheld, IMU tracking, filter
  radius 2.2 m, with Lock / GPS loss / Recovery markers.
* **Delhi & NCR** re-selected and its compiled graph re-extracted after the clean reinstall.

### Still open after this session

* **The urban profile**, above. The missing ingredient is named in `docs/03` §3.3: below about
  4 m/s the axle line is unreadable and the design hands that band to the time-domain NVE head,
  which is not implemented. Until it is, there is no speed observation at low speed and the
  stop-start case will keep diverging.
* **p90 on the tunnel.** The median (52.5 m) is inside G-2; the p90 (167 m) is not. Run-to-run
  spread is dominated by how well the spectral scale converges in the GNSS-visible approach.
* **ZIHR**, the heading half of the zero-velocity update, is still not implemented — which is
  directly relevant to the heading error above.
* **Constraint loss on delayed-fix replay.** `correct()` replays history through `advance()`, which
  re-propagates IMU only, so constraints applied during the replayed window are dropped. Bounded to
  2 s of history and only happens while GNSS is present, which is when constraints matter least.
* **On-device verification** of location acquisition time and of the new UI.

---

## 5. Work plan (execution order)

**Phase A — stop the bleeding: crash, lag, first-query cost**

- A1 — D1 route-search memory: bounded frontier and reused scratch buffers.
- A2 — D2 first-query cost: drop the redundant full-file SHA, stream validation, prebuild the
  spatial index, warm up in the background.
- A3 — D3 sensor-thread recording: binary ring buffer plus a dedicated writer thread; zero JSON on
  the hot path.
- A4 — D4 map rendering: incremental sources, throttled updates, off-UI serialisation, surface mode.
- A5 — D7 native build flags: force `-O3` and `NDEBUG` for the native target in every variant.

**Phase B — native core performance**

- B1 — D5: replace JacobiSVD with cheap re-orthonormalisation; make propagate and update in-place.
- B2 — D6: incremental repropagation with a checkpoint ladder instead of a full replay.
- B3 — D8: decimate attitude work to about 5 Hz; pre-allocate JNI buffers.

**Phase C — close the research gap on-device**

- C1 — Port CTS to C++ and emit real `SETU_FORWARD_SPEED` measurements.
- C2 — Port the SVO frontend to C++ (Tier A/B) and emit `SETU_SVO_FREQUENCY`.
- C3 — Wire NHC / ZUPT / ZIHR generators to a motion classifier.
- C4 — Add the curvature LUT to the map pipeline and emit CSA along-track and cross-track
  measurements.
- C5 — Raise the outage ceiling off the 10 s bound once C1–C4 carry the state.

**Phase D — machine learning**

- D1 — Colab notebook: dataset, physics-residual training, calibrated sigma, int8 export, parity
  tests.
- D2 — On-device LiteRT runtime behind `nn/`, with gated fusion checking validity, staleness and
  innovation.

**Phase E — evidence**

- E1 — Replay determinism, an on-device benchmark harness, the §8.6 falsification plot, and gate
  wiring in CI.

---

## 6. Live device

The testing target is a USB-debugging phone (`docs/20` references an OPPO CPH2467). `adb devices`
showed nothing attached at checkpoint time; re-check before the on-device verification passes.
