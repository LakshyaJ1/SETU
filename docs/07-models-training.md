# 07 — Models, Data Pipeline and Training

## 7.1 Model inventory

| Model | Input | Output | Params | int8 size | Latency (mid-tier phone) | Cadence |
|---|---|---|---|---|---|---|
| `TimeDomainVelNet` | 2 s IMU-feature window | `v_x`, `log sigma^2` + virtual-CAN aux heads | ~250 k | 1.1 MB | 0.8 ms | 10 Hz |
| `FamilyNet` (SVO) | spectrogram patch + harmonic-sum profile | `P(axle family)`, `f0` refinement, `log sigma^2` | ~70 k | 0.3 MB | 0.3 ms | 10 Hz |
| `MSVR` | 1 s IMU + band energies | 13-way motion class, 4-way mount quality, `p_gearchange` | ~90 k | 0.4 MB | 1.0 ms | 10 Hz |
| `AkitQNet` | 32-step history of IMU + filter state + innovations | 6 process-noise log-scale factors | ~400 k | 1.6 MB | 0.6 ms | 2 Hz |
| `VehicleClassNet` | 10 s summary features | car / two-wheeler / heavy | ~15 k | 0.2 MB | 0.1 ms | 0.1 Hz |
| `TeacherNet` | **`V-` CAN vector** | `v_x` + 128-d embedding | ~2 M | — (train only) | — | — |

Total shipped: **3.6 MB**, well inside REQ-N2's 8 MB. Total per-tick NN cost **≈2.7 ms**, inside
REQ-N1's 3 ms. These budgets are architectural constraints, not post-hoc measurements: anything that
does not fit does not ship.

## 7.2 Feature specification (the contract between trainer and runtime)

Every learned head consumes the same conditioned feature stack, defined once in
`ml/data/features.py` and mirrored in `core/dsp/features.cpp`, with a **hash of the spec stored in
the model manifest** (§5.2). Channels are chosen to be *mount-rotation invariant* wherever possible,
so the models degrade gracefully while ACE is still converging:

```
 i  channel                              invariant?   note
 0  |f|                                  yes          specific-force magnitude
 1  f . g_hat                             yes          projection on estimated gravity
 2  |f - (f.g_hat) g_hat|                yes          horizontal force magnitude
 3  omega . g_hat  ( = Omega )           yes          yaw rate about the true vertical
 4  |omega|                              yes
 5  d|f|/dt                              yes          jerk magnitude (pothole/shock cue)
 6  f_forward                             no           needs ACE
 7  f_lateral                             no           needs ACE
 8  omega_roll                            no
 9  omega_pitch                           no
10..17  band energies, 8 log-spaced bands up to Nyquist   yes   vibration/speed proxy
--- scalar context, concatenated at the head ---
   motion-class one-hot (13), mount quality (4), vehicle class (3),
   v_cts & sigma_cts, v_svo & sigma_svo, k_svo, tier one-hot (4), IMU rate
```

Channels 6–9 are zeroed (and a validity bit set) until ACE converges, so the network learns to rely
on the invariant channels first — this is what gives a sensible cold-start (REQ-N5).

## 7.3 IO-VNBD data pipeline

### Ingest

```
ml/data/
  fetch.py       git-lfs pull, or direct media.githubusercontent.com per file (see IO-VNBD_NOTES.md)
  ingest.py      Polars read, encoding='latin-1', column-name normaliser (strips units/mojibake)
  sync.py        pair V-/S- runs from "Synchronised V abd S datasets"; refine alignment by
                 maximising cross-correlation of V-.YawRate vs S-.GYROSCOPE_Z (resolves residual
                 manual-sync offset to +-0.1 s)
  label.py       build velocity/attitude/position ground truth
  windows.py     emit memory-mapped .npy shards of (features, labels, meta)
```

### Ground truth and label construction

| Label | Source | Notes |
|---|---|---|
| `v_x` (primary) | **mean of 4 wheel speeds × `R_eff`** | 10 Hz, clean, no multipath — see calibration below |
| `Omega` | `V-.YawRate` | 10 Hz, better than differentiating heading |
| position / trajectory | `V-` GPS lat/lon @10 Hz → ENU | exclude epochs listed in the dataset's GPS-loss index file |
| gear, engine speed, brake, steering | `V-` columns | virtual-CAN aux heads + SVO family labels |
| lean angle (two-wheelers) | not in IO-VNBD | from self-collected two-wheeler logs only |

**`R_eff` calibration — do not trust the tyre spec.** IO-VNBD reports wheel speed in rad/s and
velocity in km/h, so `R_eff` is recoverable by least squares per run. Two sampled epochs of `V-S1`
give:

```
epoch 1:  v = 19.969 km/h = 5.547 m/s,  mean wheel = 20.15 rad/s  ->  R_eff = 0.2753 m
epoch 2:  v = 20.272 km/h = 5.631 m/s,  mean wheel = 20.08 rad/s  ->  R_eff = 0.2804 m
```

i.e. ≈0.278 m, **not** the ≈0.30 m a 195/50R16 tyre-size calculation would suggest. Fit
`R_eff` (and a small GPS-velocity latency term) by regression over each whole run, per tyre-pressure
notation A–E from the dataset's Table 5, and treat runs marked "E" (pressure unrecorded) as a
separate group. Getting this wrong puts a 5–8 % scale bias straight into every velocity label — an
error larger than the entire accuracy target.

### Splits (leakage discipline)

Split by **driver and geography**, never randomly by window:

| Split | Contents | Rationale |
|---|---|---|
| train | driver E (`Vta*`, `Vtb*`, `Vw*`, `Vf*`), driver A (`S1`–`S4`) | the bulk; driver E is the aggressive driver, good for dynamics coverage |
| val | driver B (`V-M`), driver D (`V-Y1`, `V-Y2`) | held-out drivers |
| test | driver C (`V-St*`), plus the France (`S-T*`) and Nigeria (`S-I`) smartphone-only runs | held-out driver **and** held-out country/vehicle — the honest generalisation test |
| **screening subset (REQ-F10)** | a fixed, published list of runs with a fixed seed | so the submitted plots are exactly reproducible |

Random window splits would leak: consecutive 2 s windows from the same drive are near-duplicates,
and a random split makes any model look excellent. Report both, and say which is which.

### Augmentation (this is where mount robustness comes from)

| Augmentation | Range | Simulates |
|---|---|---|
| Random mount rotation `R_bv` | full yaw, ±25° pitch, ±25° roll | cradle geometry |
| Mid-window remount | one discontinuous rotation per 5 % of windows | knocked cradle |
| Gyro/accel bias injection | `b_g` ∈ ±0.05 °/s, `b_a` ∈ ±0.15 m/s² | device variation |
| Scale/misalignment error | ±2 % per axis, ±1° non-orthogonality | uncalibrated MEMS |
| Additive noise | matched to measured Allan-variance of 3 real phones | device tiers |
| Vibration overlay | recorded engine/road vibration library, SNR-swept | different vehicles |
| Pothole/bump injection | measured shock library, 0–3 events per window | Indian road conditions |
| Rate decimation | 400 → 200 → 100 → 50 → 10 Hz | **trains one model to serve all tiers** |
| Time warp | ±10 % | speed-profile diversity |

The rate-decimation augmentation is important and cheap: it means the same `TimeDomainVelNet` is
valid on the IO-VNBD 10 Hz stream *and* on a 400 Hz self-collected stream, with the tier one-hot
telling it which regime it is in.

## 7.4 Training stages

Train in four stages; each is independently checkpointed and independently evaluable, so a failure
in stage 3 does not invalidate stages 1–2.

### Stage 1 — Self-supervised pretraining (no labels)

Masked-reconstruction pretraining of the shared 1-D CNN encoder over **all** IMU data — IO-VNBD
`S-` plus every self-collected log, labelled or not. Mask 30 % of time steps in spans, reconstruct.
This is the LIMU-BERT / masked-autoencoder recipe now well established for IMU
[R63][R64], and it matters here because labelled vehicle IMU data is scarce while raw IMU is free:
every minute anyone drives with the collector app is a training sample.

### Stage 2 — Supervised heads with privileged distillation

```
L = NLL( v_hat, sigma_hat ; v_wheel )                 # heteroscedastic Gaussian NLL, primary
  + 0.3 * Huber( v_hat, v_wheel )                     # stabilises early training
  + 0.2 * L_can( aux_heads, V_vector )                # virtual CAN bus: 4 wheel speeds, steer, gear, brake
  + 0.1 * L_feat( student_emb, teacher_emb )          # feature distillation from TeacherNet(V-)
  + 0.2 * L_phys                                      # physics residuals (below)
  + 0.05 * L_smooth( d v_hat / dt )                   # no chattering
```

```
L_phys = || a_lat - v_hat * Omega ||_delta            # coordinated turn (car form)
       + || g*sin(phi) - v_hat * w_z ||_delta         # two-wheeler form, when VCD says two-wheeler
       + || v_y ||^2 + || v_z ||^2                    # non-holonomic
       + || integral(v_hat) - integral(v_wheel) ||    # integration consistency over the window
       + || v_hat - k_svo * f0 ||_delta               # spectral consistency (Tier A/B only)
```

Calibration of `sigma_hat` is a first-class objective, not a by-product: monitor the empirical
fraction of errors inside 1σ/2σ/3σ every epoch and reject a checkpoint whose 3σ coverage is below
98 %, following TLIO's demonstration that learned covariance can be made statistically consistent
[R4]. **A velocity estimate with a dishonest covariance is worse than a mediocre one with an honest
covariance**, because the filter will trust it.

### Stage 3 — Adaptive process noise (`AkitQNet`)

Freeze the velocity heads. Roll the RI-EKF over training trajectories with simulated outages; train
`AkitQNet` to regress `Q` scale factors that minimise trajectory error, per A-KIT [R21]. Inputs
include filter innovations, so the network learns "innovations are large and correlated → inflate
`Q`" without being told the rule.

### Stage 4 — End-to-end through the differentiable filter

Unroll 200 steps (20 s at 10 Hz) with gradient checkpointing; BPTT on

```
L_e2e = ||p_hat(T) - p_gt(T)||          final position error (the metric that matters)
      + mean_t || p_hat(t) - p_gt(t) ||
      + 0.1 * NLL terms from stage 2   (retained, to stop sigma collapse)
```

Differentiable relaxations required to make gradients flow:

- **CSA:** replace the Viterbi argmax with a softmax over the top-k path hypotheses; replace DTW with
  **soft-DTW** (`gamma = 0.1`).
- **RB-PF:** train against a single-hypothesis differentiable EKF; the particle wrapper is inference-
  only. (Fully differentiable particle filters exist [R23] but the resampling gradients are noisy and
  the added complexity is not justified here.)
- **Chi-square gates:** replace with a smooth sigmoid weight during training, hard gate at inference.

Stage 4 is what turns a collection of good regressors into a good *navigator* — the KalmanNet
insight [R20] applied to our specific measurement set.

### Optimisation defaults

AdamW, `lr = 3e-4` with cosine decay and 5 % warmup, weight decay 0.01, batch 256 windows, bf16
autocast, EMA of weights (decay 0.999) for the exported checkpoint. Stage 4 uses `lr = 3e-5` and
batch 16 trajectories. Gradient clipping at norm 1.0 — mandatory, since the physics residuals can
spike when `Omega → 0`.

## 7.5 Export and on-device parity

```
PyTorch checkpoint
  -> torch.export (ExecuTorch path)   |  -> ONNX opset 18 -> onnx2tf -> LiteRT (primary path)
  -> int8 quantisation: PTQ for MSVR/FamilyNet/VCD; QAT for TimeDomainVelNet
  -> parity harness: 10 000 held-out windows through PyTorch-float and the exported int8 model
       assert |dv| mean < 0.02 m/s AND p99 < 0.10 m/s AND no sign flips in sigma ordering
  -> latency harness on 3 real devices; assert per-model budget from 7.1
  -> emit manifest.json with feature-spec hash + per-file sha256
```

The parity assertion is expressed in *navigation* units, not in tensor MSE, because 0.02 m/s of
quantisation bias is 0.12 % of scale = 1.2 m per km — the level at which it matters.

## 7.6 Two-wheeler and cross-vehicle generalisation

IO-VNBD contains four cars and no two-wheelers, and the problem statement explicitly calls out
two-wheelers as the dominant Indian case. This is a known gap in the training data and must be
closed with self-collected data, not hand-waved:

- Collect two-wheeler logs (scooter + motorcycle, two riders, cradle and tank-bag mounts) with the
  collector app at 400 Hz plus an RTK or high-quality GNSS reference.
- The lean-form physics residual (§7.4) makes the two-wheeler head *substantially* data-efficient:
  the relation `v = g·sin(phi)/w_z` is imposed, not learned, so only the residual corrections need
  fitting.
- Cross-vehicle transfer follows the R-WhONet finding [R19] that domain shift across vehicles is
  real and that a recalibration/transfer step recovers ~32 % of the loss. We implement the same idea
  as (a) the vehicle-class conditioning input, and (b) the on-device shadow calibration of §5.7.

## 7.7 What the preliminary screening submission contains (REQ-F10)

A single notebook, `ml/eval/screening_report.ipynb`, producing:

1. Position plots for **≥6 held-out IO-VNBD outage segments** across scenario types (roundabout,
   motorway, country road, town centre, hard-brake, dirt road): ground truth vs baseline B2 vs SETU,
   with the confidence tube drawn.
2. Drift-vs-outage-duration curves at 10 / 30 / 60 / 120 / 180 s, with p50 / p90 error bars.
3. The four-channel speed overlay (wheel-odometry truth, CTS, time-domain net, fused) for one
   roundabout-rich run — the plot that demonstrates the CTS mechanism working.
4. A calibration plot: predicted `sigma` vs realised error, with 1σ/2σ/3σ coverage.
5. The **flattening test** of §8.6 — drift vs distance annotated with curvature-landmark crossings —
   which is the falsifiable core claim.
6. An honest statement of tier: these results are Tier C (10 Hz `S-` stream), with SVO disabled, and
   a note that Tier A results require the high-rate self-collected data.
