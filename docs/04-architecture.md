# 04 — Technical Architecture

## 4.1 Guiding constraints

1. **One core, two shells.** The estimator is a single portable C++20 library. The Android app and
   the headless edge engine are thin shells over it (REQ-F7). No algorithm is written twice.
2. **Replay determinism.** Every input is timestamped and logged; the core is a pure function of its
   input log. Rerunning a log must produce bit-identical output (REQ-N8). This is what makes CI,
   regression tracking and the SIH demo reproducible.
3. **Rate separation.** High-rate paths (IMU, spectral) run in a real-time thread; map, spectral
   registration and anchor matching run asynchronously and deliver *delayed* measurements that the
   filter absorbs via stochastic cloning.
4. **Graceful degradation, never a cliff.** Every module publishes a validity flag and a variance.
   The filter consumes whatever is valid. Losing a module degrades accuracy, never stability.

## 4.2 Layered view

```
+=======================================================================================+
|  L7  PRESENTATION                                                                     |
|      Android app (Compose + MapLibre)      |  Edge: gRPC / NMEA / UDP / ROS 2 out     |
+=======================================================================================+
|  L6  ORCHESTRATION                                                                    |
|      SMM Seamless Mode Manager  ---  session lifecycle, mode ramp, health, logging     |
+=======================================================================================+
|  L5  ESTIMATION                                                                       |
|      IAF:  RB-PF over road graph   {  RI-EKF on SE_2(3) x theta  }                     |
|            + learned Q (A-KIT head)  + learned measurement sigma  + gating             |
+=======================================================================================+
|  L4  MEASUREMENT GENERATORS  (all emit  <value, covariance, validity, t_stamp>)        |
|   NVE          CSA            EFA              GQM            NHC/ZUPT   Baro          |
|   velocity     along-track    magnetic/baro/   per-sat trust  kinematic  altitude      |
|   (SVO+CTS+TD) registration   radio anchors    + Doppler      constraint               |
+=======================================================================================+
|  L3  PERCEPTION / SEMANTICS                                                            |
|   MSVR motion & mount classifier | ACE alignment & calibration | VCD vehicle class      |
+=======================================================================================+
|  L2  SIGNAL CONDITIONING                                                               |
|   spectral front-end (STFT, ridge) | adaptive notch | outlier/shock rejection | resample|
+=======================================================================================+
|  L1  SENSOR HAL  (uniform, timestamped, monotonic; source-agnostic)                    |
|   Android SensorManager / SensorDirectChannel | GnssMeasurements | Barometer            |
|   External: USB-CDC / BLE / UDP / SPI FOG-MEMS | file replay                            |
+=======================================================================================+
|  L0  MAP & ANCHOR STORE  (offline)                                                     |
|   PMTiles basemap | routing graph | per-edge heading/curvature LUT | DEM | anchor DB    |
+=======================================================================================+
```

## 4.3 Capability tiers (the honest deployment matrix)

Module availability is a function of the IMU sample rate, which the HAL detects at runtime. This is
not a caveat buried in a footnote; it is a first-class architectural switch.

| Tier | IMU rate | Typical source | SVO | CTS | CSA | Expected drift, 1 km |
|---|---|---|---|---|---|---|
| **A** | ≥ 200 Hz | modern Android via `SensorDirectChannel`, external MEMS/FOG | full (orders 1–11) | yes | yes | **0.5–1 %** |
| **B** | 50–200 Hz | most Android phones via `SENSOR_DELAY_FASTEST` | partial (orders 1–4) | yes | yes | 1–2 % |
| **C** | 10–50 Hz | throttled/older devices, **IO-VNBD `S-`** | off | yes | yes | 2–3 % |
| **D** | < 10 Hz or no gyro | degraded fallback | off | off | topology only | route-extrapolation only |

The tier is reported in telemetry and shown in the app's diagnostics pane, so a benchmark number is
never quoted without the tier that produced it.

## 4.4 Module specifications

### L1 — Sensor HAL

```cpp
namespace setu {

enum class SensorKind { Accel, Gyro, Mag, Baro, GnssFix, GnssRaw, WheelTick /*edge only*/ };

struct ImuSample {                 // right-handed, SI, sensor frame
  int64_t  t_mono_ns;              // monotonic clock, NOT wall clock
  Vec3     accel_mps2;             // specific force
  Vec3     gyro_rps;
  float    temp_c;                 // for thermal bias models; NaN if unavailable
  uint32_t seq;
};

struct GnssRawEpoch {              // one per measurement epoch
  int64_t  t_mono_ns;
  std::vector<SatMeas> sats;       // svid, constellation, cn0_dbhz, pseudorange_rate_mps,
                                   // pseudorange_rate_uncert, elevation_deg, azimuth_deg,
                                   // multipath_indicator, agc_db
};

class ISensorSource {              // implemented by: Android, SerialFog, Udp, FileReplay
 public:
  virtual ~ISensorSource() = default;
  virtual Capabilities caps() const = 0;      // rates, which sensors present -> selects Tier
  virtual void start(SampleSink& sink) = 0;
  virtual void stop() = 0;
};
}
```

Requirements on the HAL: monotonic timestamps only (wall-clock jumps on NTP sync and would corrupt
integration); explicit handling of Android's per-sensor timestamp base inconsistencies; a
time-offset estimator per sensor stream (accel/gyro/mag/baro/GNSS are not co-timed on Android, and a
10 ms gyro-vs-accel skew is a 0.06° attitude error per turn).

### L2 — Signal conditioning

| Block | Spec |
|---|---|
| Resampler | Fractional-delay FIR to a canonical internal rate (200 Hz Tier A/B, native for C) |
| Spectral front-end | STFT: Hann, 512 pt @200 Hz (2.56 s), hop 20 samples (0.1 s), log-magnitude; ring buffer, zero allocation in steady state |
| Adaptive notch | 2nd-order IIR notch bank tracking estimated engine order and its 2nd/4th harmonics; **applied only on the branch feeding NVE-time-domain and NHC**, never on the branch feeding SVO |
| Shock rejection | Median + MAD detector on `d\|f\|/dt`; windows containing a pothole/bump are tagged, not deleted (deletion biases the mean) |

### L3 — Perception

```cpp
struct MotionState {               // MSVR output, 10 Hz
  MotionClass cls;                 // 13-way, see 03-approach.md 3.9
  float       p_stationary;
  MountQuality mount;              // Rigid | Soft | Loose | Handheld
  float       p_gearchange;        // feeds SVO family disambiguation
};

struct AlignmentState {            // ACE output
  Quat  q_bv;                      // phone -> vehicle
  float sigma_roll, sigma_pitch, sigma_yaw;
  bool  converged;
  int64_t t_last_remount_ns;
};

enum class VehicleClass { Car, TwoWheeler, HeavyGoods, Unknown };   // VCD; selects CTS model
```

### L4 — Measurement generators

All generators implement one interface, which is what makes the filter agnostic and the system
extensible:

```cpp
struct Measurement {
  int64_t   t_mono_ns;             // may be in the PAST -> stochastic cloning
  MeasKind  kind;                  // GnssPos, GnssDoppler, VelBody, Nhc, Zupt,
                                   // AlongTrack, CrossTrack, MagAnchor, BaroAlt, MagHeading
  VecX      z;
  MatX      R;                     // heteroscedastic, from the learned head or an analytic Hessian
  float     validity;              // 0..1, multiplies into R
  uint32_t  source_id;
};

class IMeasurementGenerator {
 public:
  virtual void onImu(const ImuSample&) = 0;
  virtual void onContext(const MotionState&, const AlignmentState&, const FilterView&) = 0;
  virtual std::optional<Measurement> poll() = 0;     // non-blocking
};
```

| Generator | Runs on | Latency budget | Output |
|---|---|---|---|
| `NveGenerator` (SVO + CTS + TimeDomainNet fusion) | RT thread + NN thread | 15 ms | `VelBody` 10 Hz |
| `CsaGenerator` | worker thread | 200 ms (delayed OK) | `AlongTrack` + `CrossTrack` 1–5 Hz |
| `EfaGenerator` | worker thread | 500 ms | `MagAnchor`, `BaroAlt` |
| `GqmGenerator` | GNSS callback thread | 5 ms | `GnssPos`, `GnssDoppler` with per-sat trust |
| `KinematicGenerator` | RT thread | 1 ms | `Nhc`, `Zupt`, `Zihr` |

**NVE fusion detail.** SVO, CTS and the time-domain network are *not* averaged. Each produces
`(v, sigma)`; they are combined by inverse-variance weighting **after** a consistency check
(pairwise chi-square). A disagreement larger than 3σ raises `sigma` for all of them rather than
picking a winner — a fault-detection posture, not a voting posture. CTS additionally emits a
calibration update for `k_svo` when it is the confident channel.

### L5 — Estimation core

```cpp
class InvariantEkf {                        // RI-EKF on SE_2(3) x R^14
 public:
  void propagate(const ImuSample&, const Mat& Q_scaled);
  bool update(const Measurement&);          // returns false if chi-square gated out
  State state() const; Cov cov() const;
  Clone clone(int64_t t_ns) const;          // stochastic cloning for delayed measurements
};

class RoadParticleFilter {                  // RB-PF wrapper
 public:
  void step(const ImuSample&, std::span<const Measurement>);
  Pose mapPose() const;                     // MAP particle, never a multi-modal mean
  ConfidenceTube tube() const;              // for the UI
 private:
  struct Particle { PathHypothesis path; InvariantEkf ekf; double logw; };
  std::vector<Particle> parts_;             // 64 phone / 256 edge
};
```

Numerical policy: `double` for the covariance and the Lie-group state; `float` for network I/O;
covariance kept symmetric-positive-definite via a Joseph-form update and a periodic Cholesky
re-projection. Every update is chi-square gated at 99.9 %; gated measurements are counted per source
and surfaced in health telemetry (a source with a high gate rate is a sensor fault, not noise).

### L6 — SMM Seamless Mode Manager

Not a state machine over `{GNSS, DR}` — a continuous weight ramp (see [05-system-design.md](05-system-design.md) §5.6).

### L0 — Map & anchor store

| Artefact | Format | Content | Size, one metro region |
|---|---|---|---|
| Basemap | PMTiles (vector) | rendering only | ~120 MB |
| Routing graph | custom flatbuffer | nodes, directed edges, `highway=`, `oneway`, `layer`, `tunnel`, `bridge`, `maxspeed`, turn restrictions | ~40 MB |
| **Curvature LUT** | flatbuffer, per edge | `psi_map(s)`, `kappa_map(s)` at 1 m; landmark index (curvature extrema, roundabouts, ramps) with a saliency score | ~60 MB |
| DEM | tiled int16 | elevation for baro/grade matching | ~20 MB |
| Anchor DB | SQLite | per-edge magnetic signature, baro grade, radio fingerprints, visit counts | grows with use, capped by LRU |

The curvature LUT is the artefact that makes CSA real-time: all the geometry is precomputed offline,
so online CSA is a correlation against a flat array, not a geometric query.

## 4.5 Dataflow, one 100 ms tick (Tier A)

```
t=0     IMU ring buffer holds 200 Hz accel/gyro (20 new samples since last tick)
  |
  |-- RT thread ------------------------------------------------------------------+
  |   propagate RI-EKF x20 (with Q scaled by the last A-KIT output)               |
  |   KinematicGenerator -> NHC (x20), ZUPT if stationary                         |
  |   STFT hop x1 -> new spectral frame -> SVO ridge step                         |
  +-------------------------------------------------------------------------------+
  |
  |-- NN thread (int8, XNNPACK) --------------------------------------------------+
  |   MSVR (1 ms) -> motion class, mount quality                                  |
  |   TimeDomainVelNet (0.8 ms) -> v_td, sigma_td                                 |
  |   FamilyNet (0.3 ms) -> axle-family posterior, sigma_svo                      |
  |   AkitQNet (0.6 ms, every 5th tick) -> Q scale factors                        |
  +-------------------------------------------------------------------------------+
  |
  |   CTS (analytic, RT) -> v_cts, sigma_cts   [gated on |Omega|>0.05 or lean>8deg]
  |   NVE fuse (SVO, CTS, TD) -> VelBody measurement
  |
  |-- worker thread (async, may lag 1-3 ticks) -----------------------------------+
  |   CSA: correlate psi_imu vs curvature LUT for the top-k path hypotheses       |
  |   EFA: subsequence-DTW magnetic buffer vs anchor DB                           |
  +-------------------------------------------------------------------------------+
  |
  v
RB-PF: absorb all polled measurements (delayed ones via stochastic cloning),
       reweight/resample particles, publish MAP pose + tube
  |
  v
Output at 10 Hz -> UI (60 fps by constant-acceleration extrapolation) / gRPC / NMEA
```

Total measured NN budget: **≈2.7 ms per tick**, inside REQ-N1's 3 ms.

## 4.6 Threading model

| Thread | Priority | Work | Must not |
|---|---|---|---|
| RT sensor | `SCHED_FIFO` / Android `THREAD_PRIORITY_URGENT_AUDIO` | HAL callbacks, ring-buffer writes, EKF propagate, NHC/ZUPT, STFT hop | allocate, lock, log to disk, call into JNI |
| NN | high | all TFLite/ExecuTorch invocations, fixed pre-allocated tensors | block the RT thread |
| Worker | normal | CSA, EFA, map queries, anchor DB I/O | hold a lock the RT thread wants |
| Logger | low | ring-buffer drain to protobuf-framed file | drop samples silently (must count drops) |
| UI | normal | Compose recomposition, map render, extrapolation | do any estimation |

Cross-thread transport is a single-producer/single-consumer lock-free ring per direction; the filter
is owned exclusively by one thread and mutated only through a command queue.

## 4.7 Repository layout

```
setu/
  core/                        # portable C++20, zero platform deps
    hal/                       # ISensorSource, replay, time-offset estimator
    dsp/                       # STFT, notch, ridge tracker, DTW
    geo/                       # SE_2(3), RI-EKF, Lie helpers (Eigen)
    filter/                    # InvariantEkf, RoadParticleFilter, stochastic cloning
    meas/                      # NVE, CSA, EFA, GQM, kinematic generators
    map/                       # graph reader, curvature LUT, landmark index
    nn/                        # runtime abstraction: TFLite | ExecuTorch | ORT
    api/                       # setu_engine.h  (C ABI, stable)
    tests/                     # GTest + golden replay logs
  android/
    app/                       # Kotlin, Compose, MapLibre, foreground service
    jni/                       # thin JNI over api/
    logger/                    # data-collection mode (400 Hz, raw GNSS, video-timestamped)
  edge/
    setu_daemon/               # headless: serial/UDP FOG IMU in, gRPC/NMEA out
    ros2/                      # optional ROS 2 node
  ml/
    data/                      # IO-VNBD ingest, LFS fetch, sync, outage protocol
    models/                    # PyTorch defs: TimeDomainVelNet, FamilyNet, MSVR, AkitQNet
    train/                     # Lightning + Hydra configs, PID distillation, diff-filter BPTT
    export/                    # ONNX / TFLite / ExecuTorch, QAT, per-op parity tests
    eval/                      # benchmark harness, plots, ablation runner
  maps/
    pipeline/                  # osm.pbf -> graph + curvature LUT + PMTiles + DEM
  docs/                        # this directory
```

## 4.8 The C ABI (what both shells call)

```c
typedef struct SetuEngine SetuEngine;

SetuEngine* setu_create(const SetuConfig* cfg);          /* cfg: tier hint, model paths, map dir */
void        setu_push_imu   (SetuEngine*, const SetuImu*);
void        setu_push_gnss  (SetuEngine*, const SetuGnssRaw*);
void        setu_push_mag   (SetuEngine*, const SetuVec3Stamped*);
void        setu_push_baro  (SetuEngine*, const SetuScalarStamped*);
int         setu_poll_pose  (SetuEngine*, SetuPose* out);  /* 10..200 Hz, non-blocking */
int         setu_health     (SetuEngine*, SetuHealth* out); /* tier, mode, per-source gate rates */
void        setu_destroy    (SetuEngine*);
```

`SetuPose` carries `lat, lon, alt, v_n, psi, cov[6], mode, confidence_radius_m, matched_edge_id,
along_track_s, level_index`. `mode` is a float in `[0,1]` (0 = pure DR, 1 = fully GNSS-aided), not an
enum — the UI renders the ramp instead of a flip.

## 4.9 Optional tier-3 aids (designed for, not required)

- **Camera VO.** Only where thermal budget allows and only as a *velocity* aid (scale from the
  known camera height above a locally planar road). Tunnels are visually degenerate, so this is
  weighted low there. Off by default.
- **Wheel ticks / OBD.** If a fleet operator *does* have a dongle, the same `Measurement` interface
  accepts it as a high-quality `VelBody` source, and SETU then approaches the WhONet regime [R18].
  The architecture must not preclude this even though the problem statement forbids relying on it.
- **BLE/UWB beacons.** For a fleet's own depots and parking structures, an anchor type in the same
  `EFA` slot.
