# 02 — Existing Solutions and the Gap We Attack

Reference IDs `[Rnn]` resolve in [10-references.md](10-references.md).

## 2.1 What already exists

### A. Classical model-based INS aiding (the industrial baseline)

| Technique | What it does | Reported performance | Limitation for us |
|---|---|---|---|
| Non-holonomic constraints (NHC) [R29][R30][R31] | Asserts zero lateral and vertical velocity in the vehicle frame; observes attitude and bounds lateral drift | INS/NHC in a real tunnel: **≈3.1 % of distance / km** with a phone [R56] | Requires the IMU-to-vehicle lever arm to sub-decimetre accuracy [R30]; **fails on leaning two-wheelers**; does nothing for along-track scale |
| ZUPT / ZIHR | Zero-velocity and zero-heading-rate updates at stops | Resets velocity error to ~0 at every stop | Only helps if the vehicle actually stops |
| Odometer/INS (OD/INS) | Wheel-speed aiding | 0.5–1 % of distance | **Needs the vehicle bus** — explicitly forbidden |
| u-blox UDR (commercial, closest analogue) [R58] | GNSS chip + internal 3D gyro/accel, no vehicle connection, auto-calibrating | Metre-level in urban canyon; "accurate mileage through tunnels and garages" | Proprietary, dedicated hardware, tuned to a rigidly bolted module — not a loose phone cradle; performance figures are marketing-grade, not per-km drift |

**Read on the baseline:** a *well-implemented* classical INS/NHC on a phone already reaches roughly
3 %/km, i.e. ~31 m per km — which technically passes the SIH 10 % gate. Any team that only
re-implements this will pass the benchmark and look identical to fifty other teams. The competitive
question is not "can you pass 10 %" but **"can you get to ~1 % and prove why."**

### B. Learned inertial odometry (the academic mainstream)

| Work | Idea | Result | Why it does not solve our problem |
|---|---|---|---|
| RoNIN, IONet [R1] | Regress 2D velocity/displacement from IMU windows | Strong for **pedestrians** | Pedestrian gait is quasi-periodic and self-scaling; vehicles have no equivalent periodic signature in the time domain |
| TLIO [R4] | ResNet predicts 3D displacement **plus a 3×3 covariance**, fed into a stochastic-cloning EKF | 33 % position-drift reduction; learned sigma statistically consistent (>99 % inside 3σ) | Pedestrian; but the **learned heteroscedastic covariance into a filter** pattern is the right one and we adopt it |
| AI-IMU Dead-Reckoning [R3] | CNN adapts the *measurement noise* of an invariant EKF that enforces NHC; IMU-only on KITTI | Competitive with top LiDAR/visual odometry on KITTI | Car-grade IMU rigidly mounted; still integration-based, so error accumulates on straight roads |
| OdoNet [R8] | 1D-CNN pseudo-odometer from a single IMU | **68 %** position-error reduction vs NHC alone (hardware odometer gives 74 %) | Vehicle-mounted IMU, not a phone in a cradle; needs data cleaning for mount angle and bias |
| CarSpeedNet [R7] | Speed from **accelerometer only**, smartphone | **< 0.72 m/s** error | 0.72 m/s at 16.7 m/s is 4.3 % → 43 m per km. Not enough on its own |
| MDPI 2025 smartphone speed net [R11] | Accel+gyro, body-frame, no rotation to nav frame | **0.38 m/s RMSE**, orientation-robust | 2.3 % → 23 m per km. Better, still integration-free only in speed |
| Freydin & Or [R6] | Speed from IMU for DR navigation | Lightweight, real-time | Same family, same ceiling |
| WhONet / R-WhONet [R18][R19] | Learn the *uncertainty in wheel-speed measurements*; evaluated on **IO-VNBD** at 30/60/120/180 s outages over 493 km | Up to **93 %** error reduction vs the physics model; transfer learning adds 32 % cross-vehicle generalisation | **Consumes CAN wheel speeds** — unavailable to us at inference. It is, however, the ideal *teacher* (§3.6) and the correct accuracy ceiling to quote |
| PiDR [R12] (2026), GNIO [R13] (2026) | Physics-informed residuals / gated recurrence in the network training loop | > 29 % improvement over black-box learning | Confirms the physics-informed direction; still platform-level DR without a map |

### C. Learned filtering and fusion

KalmanNet [R20] learns the Kalman gain through a differentiable filter; A-KIT [R21] regresses
**process-noise scale factors** with a transformer inside an EKF and beats a conventional EKF by
49.5 % and a model-based adaptive EKF by 35.4 %; differentiable particle filters [R23] and
differentiable factor graphs [R24] make the whole estimator trainable; 2026 work adds recurrent
meta-adaptation of UKF sigma-point weights [R25], neural-assisted UKFs for ground vehicles [R26] and
learned memory attenuation in Sage–Husa filters [R27]. **Consensus of this literature: the network
should shape the filter's uncertainty, not replace the filter.** We take that as settled and build on it.

### D. Map matching

Newson & Krumm's HMM map matching [R33] is the workhorse; ST-Matching [R34] handles sparse GPS;
DeepMM [R35] and DiffMM [R36] (2026, one-step diffusion) push learned matching. Crucially, **every
one of these consumes noisy *positions* and asks which road they lie on.** During a GNSS blackout we
have no positions to feed them — only shape. Two papers come close to what we need:
heading–length sequence matching for proprioceptive localisation [R37] and map-aided dead reckoning
from OBD speed [R38] — but **both assume a known speed source** (odometer/OBD) and therefore a known
arc length. Nobody solves the *scale-free* registration problem.

### E. Environmental anchoring in tunnels

The tunnel-positioning review [R42] surveys magnetic, UWB, Wi-Fi/BLE, leaky coaxial cable,
visual/LiDAR and 5G. Magnetic-signature matching works: long-tunnel vehicle positioning by
magnetic fingerprint [R41], train localisation from magnetic signatures in tunnels [R43], and
odometry-assisted magnetic matching [R44]. All of them, however, presuppose a **professionally
surveyed magnetic map** built by a dedicated vehicle, and none run on a consumer phone as part of an
online navigation filter.

### F. Signal-processing speed estimation (the forgotten branch)

A Linköping thesis, *Vehicle Speed Tracking Using Chassis Vibrations* [R46], shows that
**wheel-axle rotation produces a chassis-vibration fundamental proportional to vehicle speed**, and
tracks it with subharmonic summation — explicitly motivating "stand-alone road vehicle navigation in
tunnels". Related: accelerometer-based wheel odometry [R47] and engine-speed extraction from
vibration and acoustics [R48]. This literature is essentially **absent from the deep-learning
inertial-navigation conversation**, and it is the single largest untapped source of *non-accumulating*
speed information on a smartphone.

### G. What ships today in consumer navigation

Google Maps, Apple Maps and Mappls all do *some* tunnel bridging — typically constant-velocity
extrapolation along the routed polyline plus map snapping. The visible failure modes are exactly the
ones the problem statement names: the marker freezes, jumps at tunnel exit, or slides at the wrong
speed and announces the exit late. They are conservative because they must work on every device
with no calibration, and because they do not use the phone IMU aggressively.

## 2.2 The gap, stated precisely

Draw the two axes of the field:

```
                     integration-based                 registration-based
                     (error grows with time)           (error does not accumulate)
  no map     | strapdown INS, IONet/RoNIN,       |  spectral speed tracking [R46]
             | TLIO, AI-IMU, OdoNet, CarSpeedNet |  (never used for navigation)
             |                                   |
  with map   | map-aided DR from OBD speed [R38],|  ← EMPTY —
             | HMM-MM on GNSS positions [R33]    |  scale-free shape registration
             |                                   |  + crowdsourced field anchors
```

Four concrete, checkable gaps:

- **G1 — Speed is always obtained by integrating acceleration or by regressing it in the time
  domain.** Both inherit accelerometer bias. Nobody reads the *frequency* content, where the axle
  literally encodes ground speed with no integration and therefore no accumulation.
- **G2 — The map is used only as a position corrector, never as a ruler.** Existing map matching
  needs positions. During an outage the informative quantity is trajectory *shape*, and the unknown
  is *scale*. No published system solves shape-to-map registration with unknown scale.
- **G3 — Centripetal observability is left on the table.** In any turn, lateral specific force and
  yaw rate jointly determine speed exactly (`v = a_lat / omega`). This is textbook and almost never
  used as a filter measurement, and it is never adapted to leaning two-wheelers, which invert the
  relation.
- **G4 — Nobody exploits IO-VNBD's synchronised CAN stream as privileged supervision.** Teams train
  against GPS speed and inherit its noise, latency and outages, when a clean 10 Hz four-wheel
  odometry signal sits in the same folder.

## 2.3 How SETU answers each gap

| Gap | SETU mechanism | Doc |
|---|---|---|
| G1 | **SVO — Spectral Virtual Odometer.** Track axle/tyre harmonic ridges in the accelerometer spectrogram; speed from frequency, bias-free and non-integrating | §3.3 |
| G2 | **CSA — Curvature-Signature Alignment.** Register the gyro-derived heading-vs-arclength signature against the OSM road manifold with arc length as the latent variable; the map becomes the ruler | §3.5 |
| G3 | **CTS — Coordinated-Turn Speedometer**, with vehicle-class-aware lean physics for two-wheelers | §3.4 |
| G4 | **PID — Privileged-Information Distillation.** `V-` CAN wheel speeds and steering supervise a phone-only student; a "virtual CAN bus" multi-task head | §3.6 |
| — | **IAF — Invariant Adaptive Fusion.** Right-invariant EKF with learned heteroscedastic measurement noise and learned process noise, wrapped in a Rao–Blackwellised particle filter over the road graph | §3.7 |
| — | **EFA — Environmental Fingerprint Anchors.** On-device, crowdsourced magnetic and barometric anchors; first pass builds them, later passes get absolute along-track fixes | §3.8 |

## 2.4 Honest competitive positioning

What we are **not** claiming: that a neural network beats physics. It cannot. Double integration of
a biased signal diverges no matter what network wraps it.

What we **are** claiming, and what the design makes falsifiable: SETU injects **three independent
sources of non-accumulating information** that the state of the art does not use
(spectral axle frequency, scale-free map-shape registration, environmental field anchors), and fuses
them in a consistency-preserving invariant filter. Error therefore becomes bounded by *registration
precision* rather than by *elapsed time*. That is a structural change in the error law, not a
tuning improvement — which is why an order-of-magnitude gain over the ≈3 %/km smartphone state of
the art [R56] is a reasonable target rather than a boast.

The falsifiable prediction, and the thing to test first: **error should stop growing with outage
duration once a curvature landmark or a magnetic anchor is crossed.** If the drift-vs-time curve
does not flatten at landmarks, the central thesis is wrong and we fall back to the classical stack.
That experiment is specified in [08-evaluation.md](08-evaluation.md) §8.6.
