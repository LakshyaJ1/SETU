# 06 — Technology Stack

Versions are the ones to pin at project start (mid-2026). Where a choice is contested, the rejected
alternative and the reason are given, because those reasons are the ones a reviewer will ask about.

## 6.1 Estimation core (the thing that must never be rewritten)

| Concern | Choice | Rationale / rejected alternative |
|---|---|---|
| Language | **C++20** | One implementation for Android (JNI), Linux edge, and the offline replay harness. Rejected: Rust (excellent, but the Android NDK + Eigen + TFLite C API path is far better trodden in C++, and the team's SIH timeline does not have room for FFI archaeology); Kotlin/Python (cannot meet the 200 Hz edge target or the RT-thread constraints) |
| Linear algebra | **Eigen 3.4** header-only, fixed-size types on the hot path | No allocation in steady state. Rejected: hand-rolled math (bug farm), BLAS (wrong granularity for 23×23) |
| Lie groups / manifolds | **manif** (header-only) or a vendored 400-line `SE_2(3)` implementation | `SE_2(3)` with the right-invariant error is not in most libraries; keep it small, tested and ours. Reference implementations: `navlie` (Python) for cross-checking |
| Build | **CMake 3.28** + Ninja; `FetchContent` for deps | Same tree builds `.so`, static lib and CI binary |
| Serialisation | **FlatBuffers 24.x** (map artefacts, zero-copy mmap), **protobuf 4.x** (logs, gRPC) | Map LUTs must be mmap-able and read without parsing; logs need schema evolution |
| Tests | **GoogleTest** + golden replay logs + a property-based fuzzer on the filter | REQ-N8 determinism is a test, not an aspiration |
| Sanitisers | ASan/UBSan/TSan in CI; `-ffast-math` **forbidden** | Determinism requires IEEE semantics |

## 6.2 On-device inference

| Concern | Choice | Rationale |
|---|---|---|
| Primary runtime | **LiteRT (TensorFlow Lite) with XNNPACK** | Smallest, most predictable CPU latency for the tiny (<2 MB) 1-D convolutional and GRU heads we actually ship; int8 quantisation gives roughly 2× over FP with negligible quality loss, and CPU-only avoids GPU/NNAPI delegate availability roulette across Indian device SKUs |
| Secondary runtime | **ExecuTorch** | PyTorch-native export path, strong 2026 benchmarks against ORT and LiteRT [R60], and useful on the Arm edge target (SME2 acceleration [R62]). Kept behind the same `nn/` abstraction so either can be selected per model |
| Rejected | ONNX Runtime Mobile | Fine, but a third dependency for no measured gain at our model sizes; kept as a debugging export target only |
| Rejected | GPU / NNAPI delegate by default | Delegate initialisation latency and driver variance across low-end Snapdragon/MediaTek parts exceed the entire 3 ms budget; opt-in only |
| Quantisation | **int8 post-training + QAT** for the velocity head | The velocity head is the accuracy-critical one; PTQ is enough for MSVR/FamilyNet/VCD |
| Parity testing | per-op tolerance harness: PyTorch float ↔ exported int8, on the same 10 000 windows | A 0.1 m/s quantisation bias on the velocity head is 0.6 % of scale = 6 m/km. This test is not optional |

## 6.3 Training

| Concern | Choice | Notes |
|---|---|---|
| Framework | **PyTorch 2.5+**, `torch.compile` for training throughput | Differentiable filter needs autograd through a loop; PyTorch is the pragmatic choice |
| Training harness | **PyTorch Lightning 2.x** + **Hydra 1.3** | Every experiment is a config; ablations (§8.5) are config sweeps, not code edits |
| Data | **Polars** for CSV ingest, **NumPy** + memory-mapped `.npy` shards for windows | IO-VNBD is ~2 GB of CSV; Polars ingest with explicit `latin-1` encoding and a column-name normaliser handles the mojibake headers |
| Geodesy | **pyproj 3.6**, **pymap3d** | ENU frames, geodetic↔ECEF; never hand-roll the ellipsoid |
| Filter prototyping | **navlie** / custom NumPy RI-EKF | Cross-validate the C++ filter against a Python twin on the same log — catches sign and Jacobian errors that unit tests miss |
| Signal processing | **scipy.signal**, **librosa** (STFT experimentation only) | Production STFT is hand-written C++ for determinism |
| Map / graph | **pyrosm** or **osmium-tool** + **osmnx** (analysis), **shapely 2.x**, **networkx** | Offline pipeline only |
| Map matching baselines | **fmm** (Fast Map Matching), **leuvenmapmatching**, **mappymatch** | Needed as *baselines* in §8.4, not in the product |
| Tracking | **MLflow** (self-hosted; works offline) or Weights & Biases | Every result in §8 must be reproducible from a run ID |
| DVC / git-lfs | dataset and bundle versioning | IO-VNBD is already LFS; keep the discipline |

## 6.4 Android application

| Concern | Choice | Notes |
|---|---|---|
| Language / UI | **Kotlin 2.0**, **Jetpack Compose**, Material 3 | |
| Min / target SDK | **26 / 35** | API 26 for `SensorDirectChannel`; raw GNSS (`GnssMeasurementsEvent`) needs API 24+ and hardware support, degraded gracefully when absent |
| Sensors | `SensorManager` with `SENSOR_DELAY_FASTEST`; **`SensorDirectChannel` + `RATE_VERY_FAST`** where reported | Achieved rate is device-dependent (typically 100–500 Hz; up to ~800 Hz on direct channels) → this is what selects the capability tier at runtime |
| GNSS | `LocationManager` + `GnssMeasurementsEvent` + `GnssStatus` (incl. `CONSTELLATION_IRNSS` for **NavIC** [R54][R59]) | Raw measurements are what make GQM possible |
| Maps | **MapLibre GL Native (Android)** with **PMTiles** offline source | Rejected Google Maps SDK: no offline vector tiles, no styling control, licence friction for a benchmark app. Rejected Mapbox: licence/cost |
| Routing (offline) | **GraphHopper** (embeddable, Java/Kotlin-friendly) or **Valhalla** via JNI | Only needed for the turn-by-turn layer; the estimator uses our own graph |
| Persistence | **Room / SQLite** (trips, anchors), protobuf files (logs) | |
| Background execution | Foreground service + `WakeLock`, `FOREGROUND_SERVICE_LOCATION` | Android will otherwise throttle sensors when the screen is off — the exact condition a driver is in |
| DI / async | Hilt, Kotlin coroutines + `Flow` | UI only; estimation stays on native threads |
| Charts (diagnostics) | Compose canvas, hand-drawn | The 4-trace speed overlay is the demo's money shot; no chart library needed |

## 6.5 Edge engine

| Concern | Choice |
|---|---|
| Targets | aarch64 Linux (Jetson Orin Nano / Raspberry Pi 5 / i.MX8M Plus), x86-64 for CI |
| Serial / transport | libserialport or raw termios; UDP protobuf; optional SPI for board-level MEMS |
| Output | **gRPC** streaming (primary), **NMEA-0183** GGA/RMC/VTG (legacy consumers), **ROS 2 Jazzy** node (optional) |
| Packaging | static binary + systemd unit; Debian package; optional Docker for x86 CI |
| Config | YAML (single file, schema-validated at start) |
| IMU classes supported | consumer MEMS (ICM-42688, BMI270), industrial MEMS (ADIS16505), **FOG** (KVH DSP-1760, Fizoptika) at 200 Hz–1 kHz |

## 6.6 Offline map pipeline

| Stage | Tool |
|---|---|
| Extract / filter | `osmium-tool` (tags-filter, extract by bbox/poly) |
| Graph build | Python + `pyrosm`, emitted as FlatBuffers |
| Geometry / curvature | NumPy + `shapely` + Savitzky–Golay; 1 m densification |
| DEM | CartoDEM / SRTM 1-arc-second, GDAL for tiling |
| Basemap tiles | `tippecanoe` → `pmtiles` |
| Validation | round-trip test: sample 1000 random edges, recompute `psi(s)` from the LUT, compare against the source geometry within 0.1° |

## 6.7 CI/CD and quality gates

```
on PR:
  build core (gcc, clang, NDK) + ASan/UBSan unit tests
  replay 12 golden logs -> assert bit-identical output hashes        (REQ-N8)
  run the benchmark harness on the IO-VNBD screening subset
  assert no regression: p50/p90 drift, per-scenario, vs the last green commit
  model export parity test (float vs int8) within tolerance
  Android: assemble debug, instrumented sensor-replay test on an emulator
nightly:
  full IO-VNBD sweep (all outage durations) + ablation matrix + plots -> MLflow
  device farm: 3 real phones (high/mid/low tier), 30 min replay each, battery + thermal report
```

The "no regression in p90 drift" gate is the one that keeps the project honest — accuracy work has a
strong tendency to improve the median while ruining the tail, and the tail is what a driver notices.

## 6.8 Hardware for development and demonstration

| Item | Purpose |
|---|---|
| 3 Android phones spanning tiers (e.g. a recent Snapdragon 8-class, a mid Snapdragon 6/7-class, a low-end MediaTek) | Tier A/B/C validation; NavIC-capable SKU for L5 |
| Rigid cradle + a deliberately soft cradle + cup-holder | mount-quality classifier training and honest failure demos |
| Reference truth: RTK GNSS receiver (u-blox ZED-F9P + antenna) or a VBOX-class logger | Ground truth for self-collected data. Without RTK-grade truth, sub-metre claims are unverifiable |
| OBD-II BLE dongle | *training-time only* teacher channel to mirror IO-VNBD's `V-` stream on our own vehicles |
| External IMU: ADIS16505 eval board; borrowed/loaned FOG if available | REQ-F7 / REQ-P5 evidence at 200 Hz |
| Barometer-capable phones | EFA baro validation (not all low-end SKUs have one) |
| Test sites | a road tunnel or long underpass, a multi-level parking structure, a skyscraper canyon, a tree-canopy road; plus a Faraday-style simulated blackout (GNSS antenna disconnect / shielded box) for repeatable trials |

## 6.9 Third-party licence posture

| Component | Licence | Note |
|---|---|---|
| Eigen | MPL2 | fine for static linking |
| MapLibre GL Native | BSD-3 | the reason to prefer it over Mapbox |
| PMTiles | BSD-3 | |
| OpenStreetMap data | ODbL | attribution required in-app; derived curvature LUT is a derived database — keep the attribution and share-alike obligations documented |
| GraphHopper | Apache-2.0 (core) | check the routing-profile modules being used |
| Valhalla | MIT | |
| LiteRT / ExecuTorch | Apache-2.0 / BSD | |
| FlatBuffers, protobuf, gRPC | Apache-2.0 / BSD | |
| IO-VNBD | as published with the dataset [R17] | cite the Data in Brief paper in any submission |

## 6.10 What we deliberately do **not** use

- **No cloud inference.** Contradicts the problem statement and the use case (tunnels have no
  connectivity — that is the entire premise).
- **No LLM anywhere in the runtime.** Nothing here needs language; a 1.6 MB GRU beats a transformer
  API call by six orders of magnitude in latency and cannot be rate-limited.
- **No camera in the default path.** §4.9 explains the reasoning.
- **No Kalman-filter library** (e.g. a generic filter framework). The RI-EKF on `SE_2(3)` with
  stochastic cloning and per-source gating is the core intellectual property; wrapping someone
  else's generic filter would cost more than writing 800 lines of tested code.
