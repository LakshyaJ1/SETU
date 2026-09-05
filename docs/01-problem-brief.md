# 01 — Problem Brief, Decoded

> Source: SIH problem statement *"AI-ML based Intelligent Dead Reckoning system for seamless navigation"*.
> This file is the normative requirements baseline. Every later document traces back to a REQ-ID here.

## 1.1 The one-sentence problem

A commodity smartphone (no OBD-II, no wheel encoder, no external GNSS) must keep producing a
**lane-accurate, 10 Hz, continuously smooth position** while GNSS is absent for tens of seconds to
minutes — and must hand back to GNSS-aided INS the instant satellites return, without a visible jump.

## 1.2 Why this is hard (the physics, stated honestly)

Strapdown inertial navigation integrates twice. Errors therefore grow super-linearly:

| Error source | Magnitude on phone-grade MEMS | Position error after 60 s |
|---|---|---|
| Residual accelerometer bias `b_a` | 0.05–0.20 m/s² | `0.5·b_a·t²` = **90–360 m** |
| Roll/pitch (levelling) error `eps` | 0.3–1.0° | `0.5·g·eps·t²` = **92–308 m** |
| Gyro bias `b_g` (tilt leak of gravity) | 0.01–0.05 °/s | `(1/6)·g·b_g·t³` = **62–308 m** |
| Scale / velocity error `e_v` (if velocity is *aided*) | 1–5 % | `e_v·D` = **10–50 m per km** |

Read the last row against the three above: **the entire game is to convert the problem from
double integration (t², t³) into a velocity-scale problem (linear in distance), and then to bound
even that with non-accumulating spatial measurements.** Everything in this design follows from that
single observation.

Additional smartphone-specific hazards the statement calls out:

- **Unknown, drifting mount geometry.** Phone-to-vehicle rotation `R_bv` is unknown, differs per
  user, and changes mid-trip (a bump knocks the cradle; the user picks the phone up).
- **Structural vibration.** Chassis, engine and road excitation at 10–300 Hz swamps the 0.1–2 Hz
  band where vehicle dynamics live. Naive low-pass filtering also destroys the acceleration signal.
- **Non-navigation motion.** Idling, pothole shocks, speed bumps, phone handling. All look like
  acceleration to a double integrator.
- **No speed reference.** Without an odometer, forward-velocity scale is weakly observable from
  accelerometers alone in the presence of bias (the classic bias/acceleration ambiguity).
- **Two-wheelers.** A large majority of Indian road vehicles lean into turns. Leaning *breaks* the
  standard non-holonomic constraint and inverts the centripetal-acceleration relation — see §3.4 of
  [03-approach.md](03-approach.md).

## 1.3 Normative requirements

### Functional

| ID | Requirement | Source phrase |
|---|---|---|
| REQ-F1 | Auto-estimate phone→vehicle pitch/roll/yaw for dash-mount **and** cradle, online, no user action | "In-Vehicle Alignment & Calibration Engine" |
| REQ-F2 | Local model that rejects road/pothole/engine noise **and** directly estimates forward velocity from IMU | "AI Speed & Vibration Filter" |
| REQ-F3 | Bind the trajectory to a road network with kinematic constraints (UKF / HMM map-matching or AI equivalent) | "Advanced Map-Matching & Kinematic Constraints" |
| REQ-F4 | AI-based GNSS+INS fusion that removes drift when GNSS is present | "GNSS+INS Fusion Engine" |
| REQ-F5 | Transition GNSS-aided ⇄ pure DR within **milliseconds**, both directions, no position jump | "Seamless GNSS Deficit Handler" |
| REQ-F6 | Mobile app with a smooth, uninterrupted vehicle marker | "Real-time Navigation Interface" |
| REQ-F7 | Same models and engine run on **external** IMU streams (FOG-grade), not just phone sensors | "Edge deployable software engine" |
| REQ-F8 | Offline map database (OSM) usable with no network | "downloaded map database" |
| REQ-F9 | Train offline (cloud/desktop), infer on device | "On-Device Workflow" |
| REQ-F10 | Screening artefact: preliminary models plus position plots inferred on an IO-VNBD subset | "part of their proposals" |

### Performance (acceptance gates)

| ID | Metric | Target | Notes |
|---|---|---|---|
| REQ-P1 | Horizontal drift during GNSS blackout | **< 10 % of distance travelled** | hard ceiling |
| REQ-P2 | Short blackout | **< 5 m over 50 m in < 1 min** | low-speed / creep regime |
| REQ-P3 | Long blackout | **< 100 m over 1 km @ 60 km/h** | tunnel / metro underpass |
| REQ-P4 | Output rate, phone | **10 Hz** position and velocity | UI at 60 fps by extrapolation |
| REQ-P5 | Output rate, edge + FOG IMU | **≈ 200 Hz** | same core, different HAL |
| REQ-P6 | Mode-switch latency | **< 100 ms**, no discontinuity | REQ-F5 |

**Internal targets — what we actually design for, 5–10× tighter than the gate:**

| Metric | SIH gate | SETU internal target | Rationale |
|---|---|---|---|
| 1 km tunnel @ 60 km/h | < 100 m | **< 15 m (1.5 %)** | the best published *smartphone* INS/NHC tunnel result is ≈3.1 %/km [R56]; the goal is to beat the literature, not the gate |
| 50 m creep, < 1 min | < 5 m | **< 1.5 m** | ZUPT plus spiral-ramp curvature registration |
| Cross-track error on a mapped road | — | **< 1.5 m (lane-level)** | manifold constraint |
| Along-track error after a curvature landmark | — | **< 8 m, non-accumulating** | registration, not integration |

### Non-functional

| ID | Requirement | Budget |
|---|---|---|
| REQ-N1 | Total inference cost | ≤ 3 ms per 10 Hz tick; ≤ 6 % of one performance core |
| REQ-N2 | Model footprint | ≤ 8 MB for all heads, int8 |
| REQ-N3 | Battery | ≤ 6 %/h additional drain, screen off, foreground service |
| REQ-N4 | RAM | ≤ 180 MB RSS including map tiles |
| REQ-N5 | Cold start to DR-ready | ≤ 20 s of driving |
| REQ-N6 | Offline map, one metro region | ≤ 250 MB (PMTiles + routing graph + curvature LUT) |
| REQ-N7 | Privacy | no raw trajectory leaves the device without opt-in; anchors stored as local hashes |
| REQ-N8 | Determinism | bit-identical replay from a recorded sensor log (required for CI and demo reproducibility) |

## 1.4 Explicit non-goals

- **Not a VIO/SLAM system.** The camera is an optional tier-3 aid (§4.9 of the architecture), never
  required. Thermal and battery cost is prohibitive for a multi-hour delivery shift, and tunnels are
  visually degenerate (repetitive walls, low texture, moving light).
- **No dependence on RSU / UWB / leaky-feeder / 5G infrastructure.** Those genuinely solve tunnels
  [R42] but do not exist at scale on Indian roads.
- **No dependence on the vehicle bus.** Avoiding it is the entire point of REQ-F1/F2.

## 1.5 Dataset reality check (this shapes the architecture)

IO-VNBD [R17] provides two synchronised streams. The critical, easily-missed facts:

| Stream | Rate | Contents | Role in SETU |
|---|---|---|---|
| `V-*` (CAN via VBOX) | **10 Hz** | 4× wheel speeds, steering angle, yaw rate, indicated accel, gear, brake, GPS @ 10 Hz | **privileged teacher** and ground truth |
| `S-*` (smartphone) | **10 Hz** IMU, **1 Hz** GPS | accel, gravity, gyro, magnetometer, orientation | **student input** |

Consequences, stated up front so no reviewer has to discover them:

1. **The `S-` IMU is 10 Hz, so Nyquist is 5 Hz.** Axle-rotation harmonics (8–30 Hz at road speed)
   are aliased away. Our frequency-domain odometer (§3.3) therefore **cannot be trained or validated
   on IO-VNBD smartphone data**; it needs ≥100 Hz, ideally 400 Hz. Hence the **capability tiers** in
   §4.3, and validation of the spectral module on self-collected high-rate logs — which the problem
   statement explicitly permits and expects.
2. **`V-` GPS at 10 Hz is usable as outage ground truth. `S-` GPS at 1 Hz is not.** For `S-`
   experiments we take truth from the synchronised `V-` GPS.
3. **`S-` GPS repeats between fixes** (a 1 Hz field held across 10 rows). Decimate before using it
   as a label, or the loss is dominated by a staircase artefact.
4. **Wheel speeds are a far better velocity label than GPS-derived speed** — 10 Hz, no multipath,
   no filter latency. Most teams will regress against GPS speed. We regress against wheel odometry
   via privileged distillation (§3.6). This is the single highest-leverage use of this dataset.
5. Header encoding in `S-*.csv` is mojibake (`m/s?`, `Î¼T`). Tyre pressure varies per run
   (notation A–E, where "E" means unrecorded), which matters because wheel-speed→distance conversion
   depends on effective rolling radius.

See [../IO-VNBD_NOTES.md](../IO-VNBD_NOTES.md) for the full schema, LFS retrieval procedure and
per-driver inventory.
