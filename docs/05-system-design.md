# 05 — System Design

## 5.1 Deployment topology

```
   OFFLINE / CLOUD  (apriori, per the problem statement's hybrid workflow)
   +-------------------------------------------------------------------+
   |  IO-VNBD + self-collected logs  ->  ml/data  ->  training (GPU)   |
   |  osm.pbf + DEM  ->  maps/pipeline  ->  graph + curvature LUT      |
   |  outputs: model bundle (int8) + map bundle (PMTiles/graph/LUT)    |
   +-------------------------------------------------------------------+
                    |  signed bundles, side-loadable (works air-gapped)
                    v
   ON DEVICE
   +---------------------------------+     +-----------------------------+
   |  Android app  (SETU Navigator)  |     |  Edge daemon (setu_daemon)  |
   |  phone IMU/GNSS/mag/baro        |     |  external MEMS or FOG IMU   |
   |  Tier A/B/C, 10 Hz out          |     |  Tier A, 200 Hz out         |
   |  same core/ library via JNI     |     |  same core/ library, native |
   +---------------------------------+     +-----------------------------+
                    |                                   |
                    v                                   v
        UI + local trip store             gRPC / NMEA-0183 / UDP / ROS 2
                    |
                    v (opt-in only)
        anchor aggregation service  (per-edge signatures, never trajectories)
```

Nothing in the runtime path requires connectivity. Model and map bundles are files; for the SIH
finale they are pre-loaded and the device can run in airplane mode with GNSS on.

## 5.2 Bundle formats

```
model-bundle-v1/
  manifest.json          { version, tier_min, input_spec, quant, sha256 per file }
  msvr_int8.tflite               ~0.4 MB
  timedomain_vel_int8.tflite     ~1.1 MB
  familynet_int8.tflite          ~0.3 MB
  akit_q_int8.tflite             ~1.6 MB
  vehicle_class_int8.tflite      ~0.2 MB
  calib_priors.json      { per-vehicle-class R_eff prior, gyro/accel Allan params }

map-bundle-v1/<region>/
  basemap.pmtiles
  graph.fb               nodes, directed edges, attributes, turn restrictions
  curvature.fb           per-edge psi(s), kappa(s) @1 m + landmark index + saliency
  dem.tiles
  anchors.sqlite         (created on device; shipped empty)
```

`manifest.json` pins `input_spec` (channel order, units, window length, normalisation constants). A
mismatch between the trainer's and the runtime's channel order is the single most common silent
failure in this class of system, so the runtime **refuses to load** on a spec hash mismatch.

## 5.3 Map pipeline (offline)

```
osm.pbf --osmium--> filtered ways (highway=* minus footway/path/steps)
       |
       +--> graph builder ------> graph.fb        (nodes, directed edges, oneway, layer,
       |                                           tunnel, bridge, maxspeed, junction=roundabout)
       +--> geometry processor -> curvature.fb
       |        1. densify each edge polyline to 1 m
       |        2. smooth with a curvature-preserving spline (Chaikin + Savitzky-Golay on psi)
       |        3. psi(s) = atan2(dy, dx);  kappa(s) = dpsi/ds
       |        4. landmark index: local extrema of |kappa|, roundabout entries/exits, ramp
       |           helices, junction nodes; saliency = |integral kappa ds| over the feature
       |           x uniqueness within a 500 m neighbourhood
       +--> DEM sampler --------> per-edge grade profile (for baro matching)
       +--> tippecanoe/pmtiles -> basemap.pmtiles
```

**Saliency matters.** A curvature landmark is only useful if it is *locally unique*: a road with ten
identical bends offers weak `s_0` observability. Precomputing uniqueness lets CSA report an honest
`sigma_s` and lets the RB-PF spawn the right number of hypotheses.

OSM quality in India is uneven. Mitigations: (a) `sigma` for the cross-track constraint is scaled by
an OSM geometry-confidence heuristic (node density, last-edit recency, `highway=` class);
(b) the RB-PF supports an explicit **off-road particle** so a missing road does not force a wrong
match — the "map is wrong" failure mode studied in [R39]; (c) an optional Mappls/other-provider
adapter behind the same graph interface, since the problem statement names MapmyIndia.

## 5.4 Android application design

### Screens

| Screen | Content |
|---|---|
| **Navigate** (primary) | Full-bleed MapLibre map, vehicle chevron, confidence tube, route line, next-turn banner, a small mode strip showing the GNSS→DR ramp as a filled bar rather than an icon flip |
| **Diagnostics** (swipe-up sheet) | Tier, IMU rate achieved, satellites with per-satellite C/N0 and trust, mount quality, alignment convergence, live speed from each channel (SVO / CTS / time-domain / GNSS) overlaid, per-source gate rates, drift estimate since last fix |
| **Drive log** | Trip list; each trip replayable and exportable as a `.setulog` for offline analysis |
| **Collect** (data-collection mode) | 400 Hz IMU + raw GNSS + optional CAN/OBD reference logging, for building training data and anchors |
| **Settings** | Region download, vehicle class override, anchor sharing opt-in, model bundle version |

The Diagnostics screen is deliberately prominent: for a jury demo, the persuasive artefact is
**four speed traces agreeing with each other while GNSS is switched off**, not a marker moving on a
map. It is also the fastest way to debug a field problem.

### Smoothness (REQ-F6)

The filter runs at 10 Hz; the display runs at 60 fps. Rendering the raw 10 Hz pose looks stuttery,
and interpolating between past poses adds 100 ms of visible lag. Instead:

```
render_pose(t_render) = extrapolate(last_pose, v, a, psi_dot, dt = t_render - t_pose)
                        projected onto the matched edge polyline
```

Extrapolation along the *road* rather than along the velocity vector is what removes the sideways
wobble that makes competitor apps look broken in tunnels. When a correction arrives, it is applied
as a **critically-damped blend over 300 ms** with a hard cap on apparent speed change, so the
marker never teleports (see §5.6).

### Battery and thermal

- Foreground service with a persistent notification; `SensorDirectChannel` where available (lower
  wake-up overhead than callbacks at 400 Hz).
- Spectral front-end is the main CPU cost. Adaptive duty cycle: drop the STFT hop rate to 5 Hz when
  GNSS is healthy and the trust vector is strong, restore to 10 Hz within one tick on degradation.
  SVO only needs to be *calibrated* before an outage, not run continuously at full rate.
- Thermal governor hook: on `THERMAL_STATUS_MODERATE`, reduce particles 64→32 and NN cadence;
  never reduce the EKF propagate rate.

## 5.5 Edge engine design (REQ-F7)

```
setu_daemon --config edge.yaml
  input:   serial:/dev/ttyUSB0@921600 (FOG, 200 Hz, custom or NMEA-like binary)
           | udp:0.0.0.0:5555 (protobuf ImuSample)
           | file:log.setulog (replay)
  output:  grpc:0.0.0.0:50051  (streaming SetuPose)
           | nmea:udp://239.0.0.1:10110  (GGA/RMC/VTG for legacy consumers)
           | ros2:/setu/odometry (nav_msgs/Odometry) + /setu/pose_with_cov
```

Targets: aarch64 Linux (Jetson Orin Nano, Raspberry Pi 5, i.MX8M), plus x86-64 for CI. Same
`core/` library, different `ISensorSource` and a different output sink. At 200 Hz the propagate step
dominates; the neural heads still run at 10–20 Hz because vehicle dynamics do not need more, and
this is what keeps a 200 Hz output rate feasible on a Pi-class CPU.

With a FOG IMU (gyro bias stability ~0.1 °/h vs a phone's ~50 °/h) the heading channel becomes
essentially error-free over an outage, so CSA's registration precision — not the IMU — becomes the
accuracy limit. The same code path, better inputs, and the architecture does not change.

## 5.6 Seamless handover (REQ-F5, REQ-P6) — the part everyone gets wrong

A boolean `if (gnss_lost) mode = DR;` produces exactly the pathology the problem statement
describes: at the tunnel mouth GNSS does not vanish, it *degrades* — a few multipath-corrupted
satellites keep producing a position that is confidently wrong, the filter follows it, and then the
switch happens 5 s late from a poisoned state.

SETU has **no mode switch**. It has a continuous trust ramp:

```
per satellite i:   tau_i = f_ML( cn0_i, elev_i, agc, prr_consistency_i, innovation_i )   in [0,1]
epoch trust:       T = g( {tau_i}, geometry/HDOP, count )                                in [0,1]
GNSS position R:   R_pos = R_nominal / max(T, eps)^2        -> smoothly to infinity
GNSS Doppler R:    R_dop = R_dop_nominal / max(T_dop, eps)^2 (T_dop degrades much later)
reported mode:     mode = EMA(T, tau = 0.5 s)                -> the UI's ramp bar
```

Properties that follow for free:

1. **No latency.** There is nothing to detect and nothing to switch; `R` is recomputed every epoch.
   The 100 ms requirement is met because the filter's behaviour changes on the next measurement.
2. **No jump on re-acquisition.** The first post-tunnel fix arrives with a large `R` (low `T`,
   because C/N0 is still recovering and innovation is large) and is absorbed as a *weak* update,
   then strengthens over the following seconds as `T` rises. The classic "snap" is an artefact of
   accepting a full-weight position update against a drifted state; inverse-variance weighting plus
   the 300 ms render blend removes it.
3. **Partial GNSS is exploited, not discarded.** With 3–4 usable satellites, `T_pos` is near zero but
   Doppler velocity is still good — so we keep a velocity aid where competitors keep nothing. This
   is the single biggest practical win in urban canyons and under forest canopy.
4. **Poisoned states are prevented.** Multipath-corrupted satellites are down-weighted *before* they
   enter the filter, so the pre-outage state is clean.

**Innovation-based cross-check.** `T` also depends on GNSS-vs-DR innovation consistency: if the
inertial/spectral/map solution and GNSS disagree beyond their joint covariance, `T` falls. Under a
jamming or spoofing attack (a named concern), the self-contained channels win and the filter rides
through — the same mechanism, no special case.

## 5.7 On-device continual calibration ("shadow calibration")

Whenever GNSS is healthy the device is generating perfectly-labelled training data for itself:
GNSS speed and course are the labels; the IMU is the input. SETU exploits this continuously:

| What is re-estimated online | Method | Timescale |
|---|---|---|
| `b_g`, `b_a`, `psi_bv`, `k_svo`, `b_baro` | filter states | seconds–minutes |
| Thermal bias curve `b(T)` | recursive least squares per device, persisted | hours–days |
| SVO harmonic weights `w_k`, `R_eff` prior | per-(device, vehicle) EMA, persisted | days |
| Time-domain velocity head **last layer only** | on-device gradient step against GNSS speed during good-GNSS driving, LR clipped, rollback on validation regression | days |
| Magnetic/baro/radio anchors | write on first traverse, refine on repeats | per route |

This is why SETU gets *better on a user's regular route*, which is precisely the fleet /
quick-commerce / ride-hailing usage the problem statement targets: the same tunnel, twice a day.
Only the final layer is adapted on device — full fine-tuning on a phone is neither necessary nor
safe, and a persisted validation set guards against drift.

## 5.8 Data schemas

### `.setulog` (recording / replay)

Length-delimited protobuf, one `LogRecord` per message, monotonic order:

```protobuf
message LogRecord {
  int64 t_mono_ns = 1;
  oneof payload {
    ImuSample     imu    = 2;   // accel, gyro, temp
    Vec3Stamped   mag    = 3;
    ScalarStamped baro   = 4;
    GnssFix       fix    = 5;
    GnssRawEpoch  raw    = 6;
    VehicleRef    canref = 7;   // optional ground-truth/teacher channel (OBD, VBOX, IO-VNBD V-)
    Annotation    note   = 8;   // "tunnel_entry", "outage_start", operator marks
  }
}
```

`VehicleRef` deliberately mirrors the IO-VNBD `V-` schema, so an IO-VNBD run and a self-collected
run become the *same* object to the training pipeline and to the replay harness.

### Anchor DB (SQLite, on device)

```sql
CREATE TABLE mag_anchor (
  edge_id      INTEGER, dir INTEGER,
  s_start_m    REAL,    s_step_m REAL,
  b_mag        BLOB,    -- int16 quantised |B| in 0.1 uT, 1 m spacing
  b_up         BLOB,    -- int16 quantised vertical component
  visits       INTEGER, quality REAL, updated_at INTEGER,
  PRIMARY KEY (edge_id, dir, s_start_m)
);
CREATE TABLE grade_anchor  (edge_id INTEGER, dir INTEGER, dh_profile BLOB, visits INTEGER);
CREATE TABLE radio_anchor  (edge_id INTEGER, cell_hash INTEGER, rssi_mean REAL, s_mean_m REAL);
```

Only rotation-invariant magnetic features are stored (`|B|` and the vertical component), so an
anchor recorded by a phone in one cradle orientation is usable by a phone in another. Nothing
personally identifying is stored; anchors are keyed by public map edge IDs.

## 5.9 Observability, telemetry, health

Exported at 1 Hz (locally always, remotely only on opt-in):

```
tier, imu_rate_hz, imu_drop_count
mode (0..1), sats_used, sats_tracked, mean_cn0, T_pos, T_dop
align_converged, sigma_yaw_deg, remount_events
mount_quality, motion_class, vehicle_class
v_svo, sigma_svo, v_cts, sigma_cts, v_td, sigma_td, v_fused, consistency_chi2
csa_sigma_s_m, csa_path_entropy, efa_last_anchor_age_s
ess (particle effective sample size), gate_rate[source]
est_drift_since_fix_m, confidence_radius_m
cpu_pct, nn_ms, batt_mah_per_h, thermal_status
```

`csa_path_entropy` and `ess` are the two numbers that tell an operator whether the map hypothesis is
healthy; `consistency_chi2` is the one that tells them a sensor has gone bad. These are the
quantities to put on a dashboard, not RMSE.

## 5.10 Failure modes and responses

| Failure | Detection | Response |
|---|---|---|
| Phone picked up mid-tunnel | MSVR `Handheld`, gravity CUSUM | freeze `psi_bv`, inflate `Q`, drop SVO, hold heading from gyro only, widen the tube; re-align on re-mount |
| Cradle slips (small rotation) | gravity CUSUM, NHC innovation | fast re-alignment (<2 s), `psi_bv` re-converges |
| Loose phone in a cup-holder | mount-quality classifier | disable SVO and NHC; fall back to time-domain + CSA; warn in UI |
| Map missing / wrong road | CSA residual high, path entropy high | off-road particle takes over; cross-track constraint disabled; log the geometry for later map feedback |
| Tunnel not in OSM | no tunnel edge in graph | topology-free mode: SVO+CTS only; still ≈1–2 %/km on Tier A |
| Stop-and-go traffic in a canyon | motion class `stationary` | ZUPT-dominated; error effectively frozen while stopped |
| Two-wheeler misclassified as a car | VCD posterior, CTS-vs-SVO inconsistency | inconsistency raises `sigma`; VCD re-evaluated on a 30 s window; both CTS models can be run and compared |
| GNSS spoofing | innovation vs self-contained solution, AGC/C-N0 signature | `T` → 0, ride on DR, flag the session |
| Thermal throttle | `THERMAL_STATUS` | reduce particles and NN cadence, keep propagate rate |
| Model/spec mismatch | manifest hash | refuse to load, fail loudly at startup |

## 5.11 Security and privacy

- Model and map bundles are signed; the loader verifies `sha256` per file against a signed manifest.
- No raw trajectory or raw IMU leaves the device unless the user explicitly enables sharing.
- Anchor sharing (opt-in) uploads *per-edge field signatures*, not trips — no timestamps, no device
  ID, minimum-k aggregation before a signature is accepted into the shared set.
- Trip logs are stored in app-private storage; export is a deliberate user action.
- The engine performs no network I/O at all. Anchor sync, if enabled, is a separate process.
