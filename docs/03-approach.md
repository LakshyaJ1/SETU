# 03 — SETU: The Approach

**SETU** — *Seamless Egomotion Tracking under Unavailable-GNSS*. Setu, "the bridge": it bridges the
GNSS gap.

## 3.1 The one idea

> **Stop integrating time. Start registering space.**

Every existing smartphone dead-reckoning system answers the question *"given acceleration, where am
I after t seconds?"* — a question whose answer degrades as t² or t³ no matter how good the network is.

SETU answers a different question: *"how far along this road am I?"* The state we care about is a
**scalar arc length `s` on a 1-D road manifold**, and we observe it with measurements whose error
does **not** accumulate with time:

| Information source | Physical quantity read | Error behaviour |
|---|---|---|
| Axle harmonic frequency in the vibration spectrum | ground speed | ∝ frequency-estimation error; **no accumulation** |
| Lateral specific force ÷ turn rate | ground speed, absolutely | ∝ sensor noise; **no accumulation** |
| Heading signature vs road geometry | absolute arc length | ∝ registration precision; **resets error** |
| Magnetic / barometric field signature | absolute arc length, level | ∝ map precision; **resets error** |
| Road centreline | cross-track position | **bounded by lane width** |

Integration is still present — it is what carries us *between* these observations — but it is
demoted from "the estimator" to "the interpolator". That is the structural change.

A useful way to see the size of the change: pure inertial position error after a 60 s outage is
90–360 m (§1.2). Velocity-aided error over the same 1 km is `e_v · D`. Registration-anchored error is
`max(e_v · d_landmark, sigma_registration)` where `d_landmark` is the *distance since the last
anchor*, not the distance since the last GNSS fix. On a real road, `d_landmark` is 100–400 m. The
error law changes from quadratic-in-time to bounded-by-anchor-spacing.

## 3.2 Frames, notation, state

| Symbol | Meaning |
|---|---|
| `n` | local navigation frame, ENU, origin at session start |
| `v` | vehicle frame: x forward, y left, z up |
| `b` | phone body frame (Android convention) |
| `R_nb`, `R_bv` | attitude phone→nav; mount rotation phone→vehicle (**unknown, slowly varying**) |
| `f_b` | measured specific force (accelerometer), phone frame |
| `w_b` | measured angular rate (gyro), phone frame |
| `Omega` | yaw rate about the **true local vertical** |
| `g` | 9.80665 m/s² (local value from a gravity model) |
| `s` | arc length along the currently hypothesised road edge |
| `e_v` | relative velocity (scale) error |
| `R_eff` | effective tyre rolling radius |

Filter state (23 dimensions, see §3.7):

```
X  = (R_nb, v_n, p_n)  in SE_2(3)          # 9
th = (b_g, b_a,                            # 6  gyro / accel bias
      psi_bv,                              # 1  mount yaw misalignment
      k_svo,                               # 1  spectral odometer scale = 2*pi*R_eff
      b_baro,                              # 1  barometer bias
      l_v)                                 # 3  IMU-to-rear-axle lever arm
                                           # + 2 for the CSA alignment pair (s0, alpha)
```

## 3.3 SVO — Spectral Virtual Odometer  *(novelty N1, answers gap G1)*

### The physics

A rolling wheel is a rotating machine bolted to the chassis. Its rotation rate is *exactly*
proportional to ground speed:

```
f_ax = v / (2*pi*R_eff)                       [Hz]      axle order 1
f_k  = k * f_ax                                          axle order k  (tyre non-uniformity, imbalance,
                                                          brake-disc runout, hub bearing)
f_tb = N_blocks * f_ax                                   tread-block passing frequency (N ~ 60-80)
f_eng= f_ax * i_diff * i_gear * n_order                  engine / driveline orders
```

The phone, resting in a cradle bolted to the same chassis, measures these lines in its
accelerometer. At `v = 16.67 m/s` (60 km/h) and `R_eff = 0.30 m`, `f_ax = 8.84 Hz`, with strong
harmonics through 30–90 Hz. So:

**The accelerometer already contains a wheel-speed sensor. It is in the frequency domain, and every
published smartphone dead-reckoning system throws it away by low-pass filtering at 5–20 Hz.**

The prior art for the signal-processing half exists — chassis-vibration speed tracking with
subharmonic summation [R46], accelerometer wheel odometry [R47], engine speed from vibration [R48] —
and it explicitly names tunnel navigation as the motivation. It has never been fused into a learned
navigation filter on a phone.

### Why this is the drift killer

Speed obtained by integrating acceleration inherits accelerometer bias, so its error **grows**.
Speed obtained from a frequency estimate has error

```
e_v = df0 / f0        (plus a slowly-varying R_eff calibration error)
```

and `df0` is set by the spectral estimator, not by elapsed time. With a `T = 2.56 s` window,
harmonic summation over `K = 8` orders and quadratic ridge interpolation, achievable `df0` is
0.01–0.05 Hz, i.e. **`e_v` = 0.1–0.6 %**. Compare: CarSpeedNet 0.72 m/s ≈ 4.3 % [R7], the best
published smartphone time-domain regressor 0.38 m/s ≈ 2.3 % [R11].

`R_eff` is the only remaining scale unknown, it drifts on the timescale of tyre pressure and load
(minutes to days, not seconds), and it is continuously re-estimated by CTS (§3.4) and by GNSS
whenever available. This is what makes the whole scheme self-calibrating without a vehicle bus.

### Algorithm

```
SVO(accel_window):                                   # 200-400 Hz in, 10 Hz out
  1. x = accel magnitude minus slow mean, Hann-windowed, T = 2.56 s, hop = 0.1 s
  2. P = |STFT(x)|^2                                 # 512-1024 pt, log-compressed
  3. for f0 in grid(1.5 .. 45 Hz, 0.02 Hz):          # candidate axle order 1
        HS(f0) = sum_{k=1..K} w_k * P_interp(k * f0) # harmonic / subharmonic summation
  4. f0_hat = argmax HS, refined by parabolic interpolation on the peak
  5. Viterbi ridge tracking over f0 across frames, with transition prior
        f0(t+1) - f0(t) ~ N( a_long(t) * dt / (2*pi*R_eff),  sigma_trans )
     (the accelerometer's own longitudinal channel supplies the dynamics prior — this is what
      rejects half/double-frequency slips, the classic failure of pitch trackers)
  6. FamilyNet(P, f0 candidates, gear-change flag) -> P(axle family | spectrum), sigma_v
  7. v_svo = k_svo * f0_hat,   k_svo = 2*pi*R_eff   (a filter state)
```

**Axle vs engine disambiguation** — the elegant part. Engine-order lines jump discontinuously at a
gear change; axle-order lines do not. A gear-shift detector (spectral discontinuity + longitudinal
jerk) therefore labels the families for free, and `FamilyNet` is trained on that self-supervised
label. On IO-VNBD, the `V-` stream provides `Gear` and `Engine Speed` directly, so the family labels
are exactly supervised (§3.6).

### Honest limits

| Condition | Effect | Mitigation |
|---|---|---|
| IMU rate < 100 Hz (incl. **IO-VNBD `S-` at 10 Hz**) | axle lines aliased, SVO unusable | capability tiers (§4.3); SVO validated on self-collected 400 Hz logs |
| `v` < ~4 m/s | `f0` < 2 Hz, window resolution insufficient | hand over to NVE time-domain head + ZUPT |
| Very smooth road, quiet EV, constant speed | weak excitation | `sigma_v` from FamilyNet rises; filter down-weights automatically |
| Phone loose in a cup-holder / on a seat | mechanical path decoupled | mount-quality classifier (§3.9) flags it and disables SVO |
| `R_eff` change (pressure, load, wear) | scale bias | `k_svo` is a filter state, observed by CTS and GNSS |

## 3.4 CTS — Coordinated-Turn Speedometer  *(novelty N2, answers gap G3)*

### Cars (and any non-leaning vehicle)

In a turn, lateral specific force and yaw rate determine speed exactly:

```
a_lat = v * Omega        =>        v = a_lat / Omega
```

Relative error: `e_v = sqrt( (sigma_a / (v*Omega))^2 + (sigma_Omega / Omega)^2 )`.

At `v = 16.67 m/s`, `Omega = 0.10 rad/s` (a 167 m radius curve), `sigma_a = 0.02 m/s²` after 1 s of
averaging and `sigma_Omega = 5e-4 rad/s`, this is **≈1.3 %** — from a single second of a single
curve, with no integration and no prior speed knowledge. Gate on `|Omega| > 0.05 rad/s (≈3 °/s)` so
the division never blows up; let `sigma_v` grow as `1/Omega` below that.

IO-VNBD is unusually rich in exactly this signal: `V-M` alone contains 30 roundabouts, and the
appendix tables list 100+ roundabouts and dozens of U-turns across the corpus. Every one is an
absolute speed measurement.

### Two-wheelers — where everyone else will be wrong

A motorcycle in a coordinated turn **leans**, so the centripetal force is taken up along the bike's
own vertical. In the body frame the lateral accelerometer channel reads ≈0 and the standard
non-holonomic constraint's assumption of a level chassis is violated. Naively applying `v = a_y/Omega`
gives *zero speed in every turn*.

The correct relations. Let `phi` be the lean angle, `|f|` the specific-force magnitude, and `w_z`
the **body-frame** yaw rate (about the bike's own up axis):

```
|f|            = g / cos(phi)                 =>   phi   = arccos( g / |f| )
Omega (true)   = w_z / cos(phi)               =>   Omega = w_z * |f| / g
a_lat (earth)  = g * tan(phi) = v * Omega

  =>   v = g * sin(phi) / w_z                                     (compact form)
       v = g * sqrt(|f|^2 - g^2) / (|f| * w_z)                    (measured form)
```

Worked check: `v = 16.67 m/s` on `R = 100 m`. `a_lat = 2.78`, `phi = 15.8°`, `|f| = 10.196`,
`w_z = 0.1604 rad/s`. Then `g·sin(phi)/w_z = 9.81 × 0.2727 / 0.1604 = 16.68 m/s`. Correct. Note the
`cos(phi)` factor matters: dropping it gives 17.3 m/s, a 4 % scale error that would show up as
40 m/km of drift.

Practical gate: `phi > 8°`, because `|f| − g` is only 0.0375 m/s² at 5° lean (below accelerometer
noise) but 0.386 m/s² at 15.8° (SNR ≈ 8 after 1 s averaging).

**Vehicle-class detection** (car / two-wheeler / bus-truck) runs as a small classifier on the
vibration spectrum, roll-rate statistics and the `|f|`-vs-`w_z` correlation pattern, and selects the
observation model. Getting this wrong is a silent 4 % scale error, which is why it is a first-class
architectural component rather than a footnote.

### The calibration cascade — why N1 and N2 are one mechanism

```
   turn detected  ->  CTS gives ABSOLUTE v  ->  calibrates k_svo (=2*pi*R_eff)
                                            ->  calibrates NVE time-domain bias
   straight road  ->  calibrated SVO CARRIES v with no accumulation
   next turn      ->  re-calibrate
```

**Turns calibrate the odometer; the odometer carries the straights.** Neither channel alone is
sufficient — CTS is unobservable on a straight road, SVO has an unknown scale — and together they
close the loop with no GNSS, no odometer and no map. This complementarity is the core of the design,
and it is why SETU can survive a long *straight* tunnel, the scenario that defeats shape-based
methods.

## 3.5 CSA — Curvature-Signature Alignment  *(novelty N3, answers gap G2)*

### Why classical map matching cannot help during an outage

HMM map matching [R33] and its learned successors [R35][R36] all take *noisy positions* and ask
which road produced them. During a blackout we have no positions. What we do have, and what is
extremely accurate, is **shape**: heading comes from a *single* integration of a bias-compensated
gyro, so after 60 s its error is ~0.6°, whereas position error is hundreds of metres.

So invert the problem. Treat the road as a curve parameterised by arc length and ask: *at what
arc length and what speed scale does my measured heading profile best explain the road's heading
profile?*

### Formulation

The offline map supplies, per directed edge `e`, a resampled heading profile `psi_map(s)` and
curvature `kappa_map(s) = d psi_map / ds` at 1 m spacing. The IMU supplies
`psi_imu(t) = psi_0 + integral(Omega dt)` and a nominal along-track distance
`s_hat(t) = integral(v_hat dt)` from NVE. Two scalars are unknown: the entry offset `s_0` and a
residual speed-scale `alpha`. Solve

```
   J(e, s_0, alpha) =  integral_t  w(t) * [ psi_imu(t) - psi_map( s_0 + alpha * s_hat(t) ) ]^2 dt
                     + lambda_a * (alpha - 1)^2
                     + graph_transition_cost(e)
```

- **coarse:** FFT-based cross-correlation / subsequence-DTW over `(s_0, alpha)` on a grid, per
  candidate path
- **fine:** two-parameter Gauss–Newton; `sigma_s0` and `sigma_alpha` come from the Hessian, so the
  measurement arrives with a *calibrated* covariance
- **discrete:** Viterbi over the road graph, emission cost `= min_{s_0,alpha} J`, transitions from
  the connectivity of the offline routing graph

Output: an along-track pseudo-measurement `s` with `sigma_s` (typically 3–12 m at a curvature
landmark), plus a hard cross-track constraint to the centreline. Equivalently one may match
curvature directly, `kappa_imu(s) = Omega(t) / v(t)` against `kappa_map(s)`, which removes the
heading-offset nuisance.

### Observability, honestly

`dJ/ds_0` carries information only where `kappa_map != 0`. **On a perfectly straight road CSA is
blind, and it must report that** — which it does, through `sigma_s` from the Hessian. This is
exactly why SVO+CTS exist. Conversely, the scenarios where CSA is strongest are the scenarios the
problem statement names:

- **Multi-level parking:** a helical ramp is a continuous, high-curvature, uniquely-shaped signature.
  Combined with the barometer's floor count, position is essentially pinned.
- **Tunnels and underpasses:** topologically 1-D. There is often exactly *one* road hypothesis, so
  cross-track error collapses to lane width and only `s` needs estimating.
- **Urban canyons:** dense junctions, frequent turns, landmarks every 100–200 m.
- **Roundabouts:** a 360° signature with a known radius — the single most informative landmark type,
  and IO-VNBD is full of them.

### Relation to prior art

Heading–length sequence matching [R37] and map-aided dead reckoning [R38] are the closest work.
**Both assume a known speed source** (OBD or an odometer), hence known arc length, and match a
metric polyline. SETU's contribution is the **scale-free** version: `alpha` is a free parameter
solved jointly with `s_0` and the path, which is what makes it usable with a phone that has no
speed sensor. Add the differentiable relaxation used at training time (§3.7) and the network learns
to output *map-consistent* velocity, not merely accurate velocity.

## 3.6 PID — Privileged-Information Distillation from IO-VNBD  *(novelty N4, answers gap G4)*

IO-VNBD's synchronised folders pair phone IMU (`S-`) with CAN bus (`V-`) for the same drive. That
makes it a textbook *learning-using-privileged-information* setup:

```
  teacher inputs (train only):  4x wheel speed, steering angle, yaw rate, gear,
                                engine speed, brake pressure, indicated accel     [V-*.csv]
  student inputs (train+infer): accel, gyro, magnetometer, gravity                [S-*.csv]
```

Three things this buys that GPS-supervised training cannot:

1. **A clean 10 Hz velocity label.** Wheel odometry has no multipath, no filter latency and no
   outages. GPS-derived speed on the `S-` stream is 1 Hz and staircase-interpolated (§1.5). Teams
   training on GPS speed are fitting their network to a label that is worse than the target accuracy.
2. **A "virtual CAN bus" multi-task head.** The student predicts the whole `V-` vector — wheel
   speeds, steering angle, gear, brake state — not just speed. Auxiliary tasks that are
   *physically caused* by the same latent vehicle state are strong regularisers, and the gear/engine
   heads directly supervise SVO's family disambiguation (§3.3).
3. **A defensible accuracy ceiling.** WhONet [R18] consumes exactly these wheel speeds and reports
   up to 93 % error reduction over the physics model on IO-VNBD outages. Distilling toward WhONet's
   input gives us a principled upper bound to quote and to close on: *"how much of the CAN-bus
   advantage can a phone recover?"* — a much sharper research question than "our RMSE is small".

Loss (per window):

```
L = L_v(student_v, wheel_odo_v)                     # primary, Huber + heteroscedastic NLL
  + lambda_1 * L_can(student_can_head, V_vector)    # virtual CAN bus
  + lambda_2 * L_feat(student_feat, teacher_feat)   # feature-space distillation (teacher net on V-)
  + lambda_3 * L_phys                               # physics residuals, see below
  + lambda_4 * L_traj                               # end-to-end position loss through the filter
```

`L_phys` enforces the relations the system is built on, in the PiDR spirit [R12]:

```
L_phys =  || a_lat - v * Omega ||          coordinated turn (car) / lean form (two-wheeler)
        + || v_y ||, || v_z ||             non-holonomic constraint
        + || d/dt(integral v) - v ||       integration consistency
        + || v - k_svo * f0 ||             spectral consistency  (Tier A/B only)
```

## 3.7 IAF — Invariant Adaptive Fusion  *(the estimator)*

### Why a right-invariant EKF

A standard EKF on Euler angles is inconsistent under large attitude error — exactly our situation at
cold start with an unknown mount. A **right-invariant EKF on `SE_2(3)`** has state-independent error
dynamics for the attitude/velocity/position block, converges from large initial errors and is the
basis of AI-IMU's KITTI-competitive result [R3]. We adopt it.

### Measurement channels

| Channel | Rate | Observes | Gate / notes |
|---|---|---|---|
| GNSS position | 1 Hz | `p` | ML quality monitor, §3.9 |
| GNSS Doppler velocity | 1 Hz | `v` | **survives with 3–4 satellites**, far more robust than position — the key to graceful degradation |
| NVE velocity (SVO + CTS + time-domain, fused) | 10 Hz | `v_x` | heteroscedastic sigma from the network |
| NHC | 10–200 Hz | `v_y = v_z = 0` | lever-arm compensated; disabled on leaning two-wheelers except in the leaned frame |
| ZUPT / ZIHR | on stop | `v = 0`, `Omega = 0` | motion classifier |
| CSA along-track | 1–5 Hz | `s` | sigma from Gauss–Newton Hessian |
| Map cross-track | 10 Hz | lateral offset from centreline | soft constraint, lane-width sigma |
| Magnetic anchor | on match | `s` | subsequence DTW, §3.8 |
| Barometer | 1–5 Hz | `p_z`, parking level | bias state |
| Magnetometer heading | 1 Hz | `psi` | anomaly-gated; useless in tunnels, so gate hard |

### Learned components inside the filter

1. **Heteroscedastic measurement covariance** from every neural head — the TLIO pattern [R4], whose
   learned sigma was shown to be statistically consistent (>99 % of errors inside 3σ). Without this,
   a good speed estimate with a bad covariance still destroys the filter.
2. **Adaptive process noise** via an A-KIT-style transformer [R21] that regresses `Q` scale factors
   from a window of IMU plus filter state. Reported gains over a fixed-`Q` EKF are large (49.5 %) and
   the mechanism is exactly what our regime needs: `Q` should differ between a smooth motorway and a
   pothole-ridden district road.
3. **End-to-end training through the filter** — BPTT on a final-position loss, the KalmanNet /
   differentiable-filter pattern [R20][R23][R24]. The networks are then optimised for *trajectory*
   accuracy, not for per-window regression accuracy.

### Multi-hypothesis wrapper: RB-PF over the road graph

A single EKF cannot represent "I am on the flyover **or** the road beneath it" — a genuinely bimodal
situation at every Indian urban interchange, and one where a Gaussian filter picks the average, i.e.
the wrong answer. So:

```
particle i = ( path hypothesis: edge sequence + s0 bin,   weight w_i )
             + an analytic RI-EKF over the continuous state, conditioned on that path
N = 64 (phone) .. 256 (edge)
resample when ESS < N/2;  spawn at junctions;  prune on CSA/EFA/baro likelihood
```

Rao–Blackwellisation keeps this cheap: only the *discrete* path is sampled; the 23-D continuous
state stays Gaussian. Reported position is the MAP particle (never a multi-modal mean), with the
particle spread published to the UI as a confidence tube.

## 3.8 EFA — Environmental Fingerprint Anchors

| Anchor | Mechanism | Precision | Notes |
|---|---|---|---|
| **Magnetic** | Per-edge 1-D signature of `\|B\|` and vertical component at 1 m spacing; subsequence-DTW of the last 100–300 m against it | 2–5 m along-track | Rotation-invariant features only, so mount-angle independent. First traversal writes; later traversals read. Tunnels are ideal: rebar, rails, fans and lighting produce a strong, stable, repeatable pattern [R41][R43] |
| **Barometric** | Hypsometric `dh` from pressure; MEMS baro noise ~2–3 Pa ≈ 0.2 m | level/floor: ~100 %; grade profile matching: metres | Parking levels are 2.8–3.2 m apart, an order above sensor noise [R45]. Also matches tunnel gradient against the DEM |
| **Radio** | Cell-ID / RSSI fingerprint per edge (tunnel repeaters) | 20–50 m | Coarse but *topologically decisive*: which bore, which branch |

**Crowdsourcing without a survey fleet** — the differentiator versus [R41] and [R43], which need a
professionally surveyed magnetic map. SETU builds anchors as a by-product of ordinary driving: the
first vehicle through a tunnel records the signature while its own position is still good (entering
from a GNSS-fixed approach, exiting to a GNSS-fixed road, so the traverse can be *smoothed*
retrospectively and the signature georeferenced accurately). Anchors are stored per-edge, opt-in,
aggregated as signatures rather than trajectories — so nothing resembling a personal trip leaves the
device. For a fleet operator (logistics, quick commerce, ride-hailing — precisely the users the
problem statement names) the same tunnel is traversed dozens of times a day, so anchor coverage on
the routes that matter converges within days.

## 3.9 Supporting engines

**ACE — Alignment & Calibration Engine (REQ-F1).** Roll and pitch come from the gravity direction
(the Android `GRAVITY` virtual sensor, or a low-passed accelerometer while quasi-static). The third
degree of freedom, mount yaw, is the interesting one, and it is solvable **without GNSS**: during any
turn, the horizontal specific-force axis that correlates with `w_z` *is* the lateral axis, because
`a_lat = v·Omega`; the orthogonal axis is forward, and its sign is fixed by requiring `v > 0`.
Refinement uses GNSS course-over-ground when available, and PCA of horizontal force over
acceleration/braking events. `psi_bv` is carried as a filter state with a random-walk model so it
tracks slow cradle creep. Re-mount events are caught by a CUSUM detector on the gravity direction in
the phone frame plus a filter-innovation spike, triggering fast re-alignment (target < 2 s).

**MSVR — Motion Semantics & Vibration Rejection (REQ-F2, first half).** A small CNN/SSM classifier
over 1 s windows emits `{engine-idle, stationary-engine-off, cruise, accelerate, brake, turn,
roundabout, pothole/bump, speed-bump, phone-handled, reverse, lane-change, parking-creep}`, plus a
**mount-quality** score (rigid cradle / soft cradle / loose in cup-holder / in pocket). Its outputs
gate everything: ZUPT on stationary, SVO disabled on loose mounts, pothole windows excluded from NVE
and NHC, phone-handled windows freezing `psi_bv`. Engine harmonics are removed by an adaptive notch
tracking the estimated engine order — and are simultaneously *used* by SVO, which is why the
architecture routes the raw high-rate stream to SVO before filtering.

**GQM — GNSS Quality Monitor (REQ-F5).** Binary "GNSS available / not available" is the wrong model
and the cause of the erratic jumps the problem statement describes. GQM consumes Android's raw
`GnssMeasurement` stream (C/N0 per satellite, pseudorange-rate consistency, elevation, AGC,
multipath indicator) and an ML NLOS/multipath classifier in the manner of [R49][R50][R51][R52], and
emits a **continuous trust vector per satellite**, not a boolean. Consequences:

- **Doppler-only aiding.** Pseudorange-rate velocity survives with 3–4 satellites and is far less
  multipath-sensitive than position. In a canyon or under foliage — where competitors see "GNSS
  degraded, discard" — we keep a velocity measurement.
- Jamming and spoofing show up as C/N0 and AGC signatures, and as innovation-consistency failures,
  so the filter can reject rather than diverge (a stated concern of the problem statement).
- **NavIC/IRNSS L5** is exposed on Android as `CONSTELLATION_IRNSS` on Qualcomm platforms
  [R54][R59]; extra L5 satellites at high elevation over India directly help canyon geometry.
- Because the trust vector is continuous, the DR handover is not a switch but a **weight ramp** —
  which is precisely how REQ-P6's "no discontinuity" is met (§5.6).

## 3.10 Error budget

Straight 1 km tunnel, 60 km/h, 60 s outage, Tier A device (≥200 Hz IMU), no magnetic anchors:

| Term | Value | Contribution to horizontal error |
|---|---|---|
| SVO speed scale error, post-CTS-calibration | 0.5 % | 5.0 m along-track |
| SVO frequency jitter, averaged over 60 s | 0.1 % | 1.0 m |
| Heading: residual gyro bias 0.01 °/s over 60 s | 0.6° | 5.2 m cross-track *before* map snap |
| Map cross-track constraint | lane width | **1.5 m** cross-track after snap |
| Map centreline geometry error (OSM) | — | 1–3 m |
| **Total (RSS)** | | **≈ 6–8 m = 0.6–0.8 % of distance** |

Same scenario with a mapped magnetic anchor mid-tunnel: along-track resets to ~3 m, total **≈ 4 m**.

Tier C device (10 Hz IMU — i.e. the IO-VNBD `S-` stream, no SVO possible):

| Scenario | Speed source | Expected drift over 1 km |
|---|---|---|
| Curvy A-road / urban, landmarks every ~200 m | CTS in turns + CSA resets | 5–15 m (0.5–1.5 %) |
| Straight motorway, no landmarks | NVE time-domain only, ~2.5 % | 20–30 m (2–3 %) |

Both pass REQ-P3 (< 100 m) with 3–20× margin. The published smartphone INS/NHC tunnel result is
≈3.1 %/km [R56], so **Tier C roughly matches the state of the art and Tier A beats it by 4–6×.**

50 m creep in a parking structure (REQ-P2, < 5 m): dominated by ZUPT-bounded velocity error and
helical-ramp curvature registration; expected **< 1.5 m**, with the barometer resolving the level.

## 3.11 Observability coverage matrix

The design rule is that **no two channels share a blind spot**. `Y` = strong, `~` = partial,
`-` = unavailable.

| Scenario | GNSS pos | GNSS Doppler | CTS | CSA | SVO | Magnetic | Baro | ZUPT |
|---|---|---|---|---|---|---|---|---|
| Long straight tunnel | - | - | - | ~ (topology only) | **Y** | **Y** (if mapped) | ~ (grade) | ~ (toll) |
| Curved tunnel / underpass | - | - | **Y** | **Y** | **Y** | Y | ~ | - |
| Multi-level parking | - | - | **Y** | **Y** (helix) | ~ (low speed) | Y | **Y** | **Y** |
| Deep urban canyon | ~ | **Y** | **Y** | **Y** | **Y** | - (noisy) | ~ | **Y** (traffic) |
| Dense forested highway | ~ | ~ | **Y** | **Y** | **Y** | ~ | ~ | - |
| Jamming / interference | - | - | **Y** | **Y** | **Y** | Y | Y | Y |

Read the "long straight tunnel" row: it is the only scenario where the geometric channels all fail,
and it is exactly the scenario SVO was designed for. Read the "jamming" row: every SETU channel is
self-contained, so an RF attack degrades nothing but the two GNSS columns.

## 3.12 Why this is not merely a bag of tricks

The modules are not independent features bolted together; each closes the observability hole of
another, and they share one estimator and one training objective:

```
             CTS  --calibrates-->  SVO  --carries-->  straight sections
              ^                     |
              |                     v
        turns / curvature      along-track s
              |                     |
              v                     v
             CSA  <--constrains--  road manifold  --bounds-->  cross-track
              |                                                    ^
              v                                                    |
             EFA (magnetic / baro / radio) --resets--> s ----------+
              |
              v
        IAF (RI-EKF + learned Q, sigma) inside RB-PF over the graph
              ^
              |
        GQM (continuous per-satellite trust) --ramps--> GNSS weight
```

One consistent probabilistic object (the RB-PF posterior), one end-to-end differentiable training
objective (final trajectory error), one set of physics residuals shared by every learned head.
That is why the whole is defensible as an architecture rather than an ensemble.
