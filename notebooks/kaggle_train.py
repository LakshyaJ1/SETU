"""Reproducible IO-VNBD ingest for the SETU notebook; no synthetic fallback."""
import concurrent.futures
import hashlib
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

DATA_COMMIT = "118939602e3422d47b8ab0807b623751c3ac135b"
DATA_PREFIX = "Synchronised V abd S datasets/Uncategorised IOVNB Dataset/"


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SETU-training"})
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def acquire_data(root):
    root.mkdir(parents=True, exist_ok=True)
    tree = json.loads(fetch(f"https://api.github.com/repos/onyekpeu/IO-VNBD/git/trees/{DATA_COMMIT}?recursive=1"))
    paths = [x["path"] for x in tree["tree"] if x["path"].startswith(DATA_PREFIX) and x["path"].endswith(".csv")]
    by_kind = {kind: {pathlib.PurePosixPath(p).stem[2:].lower(): p for p in paths
                     if f"/{kind}-Dataset/" in p} for kind in ("V", "S")}
    names = sorted(by_kind["V"].keys() & by_kind["S"].keys())

    def download(item):
        kind, name = item
        path = by_kind[kind][name]
        encoded = urllib.parse.quote(path)
        pointer = fetch(f"https://raw.githubusercontent.com/onyekpeu/IO-VNBD/{DATA_COMMIT}/{encoded}").decode()
        digest = re.search(r"oid sha256:([0-9a-f]{64})", pointer).group(1)
        size = int(re.search(r"size (\d+)", pointer).group(1))
        destination = root / f"{kind}-{name}.csv"
        if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raw = fetch(f"https://media.githubusercontent.com/media/onyekpeu/IO-VNBD/{DATA_COMMIT}/{encoded}")
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError(f"Git LFS hash/size mismatch: {path}")
            destination.write_bytes(raw)
        return {"path": path, "sha256": digest, "bytes": size, "file": destination.name}

    jobs = [(kind, name) for name in names for kind in ("V", "S")]
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for record in pool.map(download, jobs):
            records.append(record)
            if len(records) % 12 == 0:
                print(f"Verified {len(records)}/{len(jobs)} data files", flush=True)
    return names, {"repository": "https://github.com/onyekpeu/IO-VNBD", "commit": DATA_COMMIT, "files": records}


def normalise(name):
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")


def column(frame, prefix):
    matches = [c for c in frame if c == prefix or c.startswith(prefix + "_")]
    if len(matches) != 1:
        raise ValueError(f"Expected one column for {prefix}, found {matches}")
    return pd.to_numeric(frame[matches[0]], errors="coerce").to_numpy(dtype=np.float64)


def load_pair(root, name):
    v = pd.read_csv(root / f"V-{name}.csv", encoding="latin-1", low_memory=False)
    s = pd.read_csv(root / f"S-{name}.csv", encoding="latin-1", low_memory=False)
    v.columns = [normalise(c) for c in v]
    s.columns = [normalise(c) for c in s]
    wheel = np.mean([column(v, f"wheel_speed_{ax}") for ax in
                     ("front_left", "front_right", "rear_left", "rear_right")], axis=0)
    gps = column(v, "velocity") / 3.6
    sats = column(v, "no_of_gps_satellites_available")
    # Fit rolling radius using steady, moving GPS reference epochs. This calibrates labels;
    # neither GPS nor wheels are model inputs. Implausible satellite-count encodings are excluded.
    valid = (wheel > 15) & (gps > 5) & (sats >= 6) & (sats <= 40)
    valid &= np.isfinite(wheel) & np.isfinite(gps) & (np.abs(np.gradient(gps, .1)) < .5)
    ratio = gps / np.maximum(wheel, 1e-6)
    valid &= (ratio > .20) & (ratio < .40)
    if valid.sum() < 20:
        raise ValueError("Insufficient reliable GPS epochs for rolling-radius calibration")
    radius = float(np.median(ratio[valid]))
    inlier = valid & (np.abs(ratio - radius) < .015)
    radius = float(np.dot(wheel[inlier], gps[inlier]) / np.dot(wheel[inlier], wheel[inlier]))
    speed = wheel * radius

    accel = np.stack([column(s, f"accelerometer_{ax}") for ax in "xyz"], axis=1)
    gyro = np.stack([column(s, f"gyroscope_{ax}") for ax in "xyz"], axis=1)
    gravity = np.stack([column(s, f"gravity_{ax}") for ax in "xyz"], axis=1)
    imu = np.concatenate([accel, gyro], axis=1)
    elapsed = column(s, "time_since_start") / 1000
    date_col = [c for c in s if c.startswith("date_")]
    if len(date_col) != 1:
        raise ValueError("Missing unambiguous wall-clock timestamp column")
    dates = pd.to_datetime(s[date_col[0]], format="%Y-%m-%d %H:%M:%S:%f", errors="coerce")
    if dates.isna().any():
        raise ValueError("Unparseable phone wall-clock timestamps")
    ts = (dates.astype("int64").to_numpy() - dates.astype("int64").iloc[0]) / 1e9
    tv = column(v, "time_since_start_of_day")
    tv -= tv[0]
    if np.any(np.diff(ts) <= 0):
        raise ValueError("Non-increasing phone wall-clock timestamps")
    if not np.all(np.isfinite(imu)):
        raise ValueError("Non-finite IMU samples")
    # Use the correspondence in the publisher's synchronized row pairs. Phone elapsed
    # counters reset, and the two loggers' pauses differ, so subtracting their first
    # timestamp and interpolating globally silently shifts whole sections of labels.
    # Refuse unequal pairs rather than assuming their leading rows correspond.
    if len(v) != len(s):
        raise ValueError(f"Unequal synchronized row counts ({len(v)} vs {len(s)}); needs separate alignment")
    lat_v, lon_v = column(v, "latitude"), column(v, "longitude")
    lat_s, lon_s = column(s, "gps_latitude"), column(s, "gps_longitude")
    separation = 6371000 * np.sqrt(np.deg2rad(lat_v-lat_s)**2 +
        (np.cos(np.deg2rad(lat_v))*np.deg2rad(lon_v-lon_s))**2)
    finite_sep = np.isfinite(separation) & (np.abs(lat_v) < 90) & (np.abs(lat_s) < 90)
    median_sep = float(np.median(separation[finite_sep]))
    if not np.isfinite(median_sep) or median_sep > 50:
        raise ValueError(f"Published row alignment fails GPS position cross-check: median {median_sep:.1f} m")
    labels = speed
    valid = np.isfinite(labels) & (labels >= 0) & (labels <= 45)
    valid &= finite_sep & (separation <= 100)
    # Exclude windows that cross either logger's discontinuity, including duplicate
    # vehicle timestamps, rather than joining disconnected pieces of driving.
    vehicle_break = np.r_[False, (np.diff(tv) <= 0) | (np.diff(tv) > .2)]
    valid &= ~vehicle_break
    valid &= (np.max(np.abs(accel), axis=1) < 78) & (np.max(np.abs(gyro), axis=1) < 16)
    report = {"run": name, "rows": len(ts), "duration_s": float(ts[-1]), "wheel_radius_m": radius,
              "radius_calibration_epochs": int(inlier.sum()), "alignment": "publisher synchronized row correspondence; GPS position cross-check",
              "gps_alignment_median_m": median_sep, "gps_alignment_p90_m": float(np.percentile(separation[finite_sep], 90)),
              "elapsed_counter_resets": int((np.diff(elapsed)<=0).sum()), "vehicle_time_breaks": int(vehicle_break.sum()),
              "median_rate_hz": float(1 / np.median(np.diff(ts))),
              "invalid_samples": int((~valid).sum()), "max_gap_s": float(np.max(np.diff(ts)))}
    return {"name": name, "time": ts, "imu": imu.astype(np.float32), "speed": labels.astype(np.float32),
            "valid": valid, "report": report}


def window_runs(runs, window=400, rate=100, hop_s=1.0):
    windows, labels, metadata = [], [], []
    for run in runs:
        t, imu, speed = run["time"], run["imu"], run["speed"]
        duration = (window - 1) / rate
        for end in np.arange(duration, t[-1], hop_s):
            grid = end - np.arange(window - 1, -1, -1) / rate
            lo = max(0, np.searchsorted(t, grid[0], side="right") - 1)
            hi = min(len(t), np.searchsorted(t, grid[-1], side="left") + 1)
            if hi - lo < 30 or not np.all(run["valid"][lo:hi]) or np.max(np.diff(t[lo:hi])) > .2:
                continue
            x = np.stack([np.interp(grid, t[lo:hi], imu[lo:hi, c]) for c in range(6)], axis=1)
            windows.append(x.astype(np.float32))
            labels.append(np.interp(end, t, speed))
            metadata.append((run["name"], float(end)))
    if not windows:
        raise ValueError("No valid windows in split")
    return np.asarray(windows), np.asarray(labels, np.float32), metadata


import dataclasses, math, os, random
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_GPU_ALLOCATOR", "cuda_malloc_async")
import numpy as np
import tensorflow as tf
SEED = 20260912
tf.keras.utils.set_random_seed(SEED)
for device in tf.config.list_physical_devices("GPU"):
    tf.config.experimental.set_memory_growth(device, True)


@dataclasses.dataclass(frozen=True)
class Config:
    canonical_rate_hz: float = 100.0      # internal grid; inputs are resampled onto it
    window_seconds: float = 4.0
    hop_seconds: float = 1.0
    min_rate_hz: float = 10.0             # below this, refuse to predict (validity 0)
    max_rate_hz: float = 500.0
    max_speed_mps: float = 45.0           # contract caps at 100; training domain is road speed
    accel_saturation_mps2: float = 78.0   # ~8 g, typical phone full scale
    gyro_saturation_rps: float = 16.0
    batch_size: int = 256
    epochs: int = 40

CFG = Config()
WINDOW = int(round(CFG.window_seconds * CFG.canonical_rate_hz))   # 400 samples
print(f"window = {WINDOW} samples at {CFG.canonical_rate_hz} Hz")

G = 9.80665

def _rotation(yaw, pitch, roll):
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return Rz @ Ry @ Rx

def simulate_run(seconds=180.0, rate_hz=200.0, rng=None):
    """One drive. Returns (imu[N,6] phone frame, speed[N], rate_hz)."""
    rng = rng or np.random.default_rng()
    n = int(seconds * rate_hz)
    dt = 1.0 / rate_hz
    t = np.arange(n) * dt

    # --- speed profile: cruise segments joined by accelerations, braking and stops
    speed = np.zeros(n)
    v = rng.uniform(0, 20)
    target = v
    hold = 0
    for i in range(n):
        if hold <= 0:
            target = rng.choice([0.0, rng.uniform(2, 8), rng.uniform(8, 18), rng.uniform(18, 33)])
            hold = int(rng.uniform(3, 25) * rate_hz)
        rate = 2.5 if target > v else 3.5           # accelerate slower than you brake
        v += np.clip(target - v, -rate * dt, rate * dt)
        v = max(0.0, v)
        speed[i] = v
        hold -= 1

    accel_long = np.gradient(speed, dt)

    # --- heading: straights, curves, roundabouts
    yaw_rate = np.zeros(n)
    i = 0
    while i < n:
        span = int(rng.uniform(2, 20) * rate_hz)
        kind = rng.random()
        if kind < 0.55:
            omega = rng.normal(0, 0.01)                      # straight, small wander
        elif kind < 0.9:
            omega = rng.uniform(-0.25, 0.25)                 # curve
        else:
            omega = rng.choice([-1, 1]) * rng.uniform(0.3, 0.7)   # roundabout / tight turn
        yaw_rate[i:i + span] = omega
        i += span
    # A turn at a standstill is not a vehicle motion; scale the rate with speed.
    yaw_rate *= np.clip(speed / 12.0, 0.0, 1.0)
    # Tyres cap lateral acceleration. Without this the generator produced 1.4 g corners, which no
    # road vehicle takes, and the model would learn from motion it will never meet.
    lateral_limit = 0.45 * G
    bound = lateral_limit / np.maximum(speed, 1e-3)
    yaw_rate = np.clip(yaw_rate, -bound, bound)
    accel_lat = speed * yaw_rate                              # coordinated turn: a_lat = v * Omega

    # --- vibration: axle order proportional to speed, plus engine orders that jump at gear changes
    radius = rng.uniform(0.28, 0.34)
    axle_hz = speed / (2 * math.pi * radius)
    axle_phase = 2 * math.pi * np.cumsum(axle_hz) * dt
    roughness = rng.uniform(0.4, 2.0)                          # road class
    vibration = np.zeros((n, 3))
    for order, weight in ((1, 1.0), (2, 0.55), (3, 0.3), (4, 0.2)):
        amp = roughness * weight * (0.05 + 0.02 * np.clip(speed, 0, 35))
        for axis in range(3):
            vibration[:, axis] += amp * np.sin(order * axle_phase + rng.uniform(0, 2 * math.pi))
    gear = np.clip((speed / 7.0).astype(int), 0, 5)
    engine_hz = np.where(speed > 0.5, 25 + speed * 60 / np.maximum(gear + 1, 1) / 10, 12.0)
    engine_phase = 2 * math.pi * np.cumsum(engine_hz) * dt
    for axis in range(3):
        vibration[:, axis] += roughness * 0.35 * np.sin(engine_phase + rng.uniform(0, 2 * math.pi))
    vibration += rng.normal(0, 0.06 * roughness, size=(n, 3))

    # --- vehicle-frame specific force and angular rate (x forward, y left, z up)
    f_vehicle = np.stack([accel_long, accel_lat, np.full(n, G)], axis=-1) + vibration
    w_vehicle = np.stack([
        rng.normal(0, 0.02, n),
        rng.normal(0, 0.02, n),
        yaw_rate,
    ], axis=-1)

    # --- unknown mount rotation with slow creep
    base = _rotation(rng.uniform(0, 2 * math.pi), rng.uniform(-0.5, 0.5), rng.uniform(-0.4, 0.4))
    creep = rng.uniform(-0.02, 0.02, 3)
    accel = np.empty((n, 3)); gyro = np.empty((n, 3))
    step = max(1, int(rate_hz))            # recompute the rotation once a second
    for start in range(0, n, step):
        stop = min(n, start + step)
        drift = _rotation(*(creep * t[start]))
        R = drift @ base
        accel[start:stop] = f_vehicle[start:stop] @ R.T
        gyro[start:stop] = w_vehicle[start:stop] @ R.T

    # --- MEMS errors: white noise, turn-on bias and bias random walk
    accel += rng.normal(0, 0.05, (n, 3)) + rng.uniform(-0.15, 0.15, 3)
    gyro += rng.normal(0, 0.004, (n, 3)) + rng.uniform(-0.02, 0.02, 3)
    accel += np.cumsum(rng.normal(0, 1.6e-3 * math.sqrt(dt), (n, 3)), axis=0)
    gyro += np.cumsum(rng.normal(0, 5e-5 * math.sqrt(dt), (n, 3)), axis=0)

    imu = np.concatenate([accel, gyro], axis=-1).astype(np.float32)
    return imu, speed.astype(np.float32), rate_hz


def resample(imu, speed, source_rate, target_rate):
    if abs(source_rate - target_rate) < 1e-6:
        return imu, speed
    duration = len(imu) / source_rate
    n = int(duration * target_rate)
    src = np.arange(len(imu)) / source_rate
    dst = np.arange(n) / target_rate
    out = np.stack([np.interp(dst, src, imu[:, c]) for c in range(imu.shape[1])], axis=-1)
    return out.astype(np.float32), np.interp(dst, src, speed).astype(np.float32)


@tf.keras.utils.register_keras_serializable(package="SETU")
class PhysicalFeatures(tf.keras.layers.Layer):
    """Rotation-invariant features from raw phone-body accel+gyro. Input (B,T,6) -> (B,T,13)."""

    def __init__(self, alpha=0.01, **kwargs):
        super().__init__(**kwargs)
        self.alpha = alpha     # ~1.6 s time constant at 100 Hz

    def call(self, inputs):
        accel = inputs[..., 0:3]
        gyro = inputs[..., 3:6]

        # Causal exponential low-pass as a gravity estimate. cumsum form keeps it a single fused op
        # rather than a 400-step unrolled scan, which keeps the exported graph small and fast.
        steps = tf.shape(accel)[1]
        index = tf.cast(tf.range(steps), accel.dtype)
        decay = tf.pow(tf.constant(1.0 - self.alpha, accel.dtype), index)[None, :, None]
        weighted = tf.cumsum(accel / tf.maximum(decay, 1e-12) * self.alpha, axis=1)
        gravity = weighted * decay
        # Exact EMA seed: a constant input remains constant from the first sample.
        # The original blend decayed toward zero and used future window samples.
        gravity += accel[:, :1, :] * decay * (1.0 - self.alpha)

        down = gravity / tf.maximum(tf.norm(gravity, axis=-1, keepdims=True), 1e-6)
        a_vert = tf.reduce_sum(accel * down, axis=-1, keepdims=True)
        a_horiz = accel - a_vert * down
        a_horiz_norm = tf.norm(a_horiz, axis=-1, keepdims=True)
        w_vert = tf.reduce_sum(gyro * down, axis=-1, keepdims=True)
        w_horiz = gyro - w_vert * down
        a_norm = tf.norm(accel, axis=-1, keepdims=True)
        w_norm = tf.norm(gyro, axis=-1, keepdims=True)
        coupling = a_horiz_norm * w_vert

        # High-frequency residual: what is left after gravity removal carries the vibration the
        # spectral odometer will eventually read, and it is where speed information hides.
        residual = tf.norm(accel - gravity, axis=-1, keepdims=True)

        # |a|^2 - g^2 is the lateral force with no gravity direction involved: the cleanest form of
        # the coordinated-turn observable, and the quantity the loss regresses against.
        lateral = tf.sqrt(tf.maximum(a_norm * a_norm - tf.constant(9.80665 ** 2, accel.dtype), 0.0))

        return tf.concat([
            a_norm, a_vert, a_horiz_norm, w_norm, w_vert, lateral,
            tf.norm(w_horiz, axis=-1, keepdims=True),
            coupling, residual,
            a_norm - tf.constant(9.80665, accel.dtype),
            a_vert - tf.constant(9.80665, accel.dtype),
            a_horiz_norm * a_horiz_norm,
            w_vert * w_vert,
        ], axis=-1)

    def get_config(self):
        return {**super().get_config(), "alpha": self.alpha}

def build_model(window=WINDOW, channels=6):
    inputs = tf.keras.Input(shape=(window, channels), name="imu")
    features = PhysicalFeatures(name="physics")(inputs)
    x = tf.keras.layers.LayerNormalization(name="norm")(features)

    # Strided separable convolutions summarise 4 s into ~25 steps before the recurrence, which is
    # what keeps this inside the 3 ms budget in REQ-N1.
    for filters, stride in ((48, 2), (64, 2), (96, 2), (96, 2)):
        x = tf.keras.layers.SeparableConv1D(filters, 7, strides=stride, padding="same",
                                            activation="relu")(x)
        x = tf.keras.layers.BatchNormalization(momentum=0.9)(x)
    x = tf.keras.layers.GRU(96, return_sequences=False, name="gru")(x)
    x = tf.keras.layers.Dense(64, activation="relu")(x)

    # Softplus keeps speed non-negative without the dead gradient of a relu at zero.
    speed = tf.keras.layers.Dense(1, name="speed_raw")(x)
    speed = tf.keras.layers.Activation("softplus", name="speed")(speed)
    # Predict log-variance: the network says how uncertain it is, which is what the filter needs.
    log_var = tf.keras.layers.Dense(1, name="log_var")(x)

    return tf.keras.Model(inputs, tf.keras.layers.Concatenate(name="out")([speed, log_var]))


# Measured sweep on generated data: 0.10 rad/s gives 40 % coverage at a 217 % p90,
# 0.18 gives 15 % coverage at a 38 % p90. Coverage is worth less than a label that is
# not actively wrong, so gate high. docs/03 3.4 uses 0.05 for the analytic estimator,
# which can separate the longitudinal axis and so tolerates a weaker turn.
TURN_GATE_RPS = 0.18

def split_outputs(pred):
    return pred[:, 0], tf.clip_by_value(pred[:, 1], -6.0, 6.0)

def make_loss(physics_weight=0.15, huber_weight=1.0):
    huber = tf.keras.losses.Huber(delta=2.0, reduction="none")

    def loss(y_true, y_pred):
        truth = tf.reshape(y_true[:, 0], [-1])
        cts = tf.reshape(y_true[:, 1], [-1])         # coordinated-turn speed from a_lat = v * Omega
        quality = tf.reshape(y_true[:, 2], [-1])     # 1 where that fit is trustworthy, else 0
        speed, log_var = split_outputs(y_pred)

        error = truth - speed
        nll = 0.5 * tf.exp(-log_var) * tf.square(error) + 0.5 * log_var
        point = huber(tf.reshape(truth, [-1, 1]), tf.reshape(speed, [-1, 1]))

        # Agree with the turn geometry wherever the turn actually determines the speed. This is
        # what stops the network reading a corner as a slowdown, which is how the deployed model
        # fails: a 0.10 rad/s yaw halved its prediction.
        physics = quality * tf.abs(cts - speed) / tf.maximum(cts, 1.0)
        return tf.reduce_mean(nll + huber_weight * point + physics_weight * physics)

    return loss

def turn_targets(X):
    # Per-window coordinated-turn speed estimate, and whether to trust it.
    #
    # Two earlier forms were measured and rejected on generated data:
    #   * |a_horizontal| / |w| per sample - wrong whenever the vehicle accelerates through a corner,
    #     because the horizontal magnitude mixes longitudinal with lateral, and it needs a gravity
    #     direction that a sustained turn contaminates;
    #   * least squares with an intercept - the turn rate is nearly constant inside a window, so the
    #     regressor had almost no spread and the slope was noise (p90 error ~900 %).
    #
    # What works: read lateral force from the total magnitude, |a|^2 = g^2 + a_long^2 + a_lat^2, so
    # no gravity direction is involved at all (the same relation the two-wheeler lean form in
    # docs/03 3.4 uses), then fit a_lat = v * |w| through the origin, which is the correct model
    # because a coordinated turn has no intercept.
    #
    # Measured on the generator: usable on ~15 % of windows, median 3.5 % and p90 38 % error against
    # truth. That is a weak label, not a measurement - which is exactly how it is used below: a
    # modestly weighted regulariser that keeps the sign of the turn response right, gated hard so a
    # bad fit contributes nothing. The native CTS in docs/03 3.4 does far better because it knows the
    # mount and can separate the longitudinal axis; this proxy deliberately assumes neither.
    accel, gyro = X[..., 0:3], X[..., 3:6]
    a_norm = np.linalg.norm(accel, axis=-1)
    lateral = np.sqrt(np.maximum(a_norm ** 2 - G ** 2, 0.0))
    turn = np.linalg.norm(gyro, axis=-1)                 # |w|, rotation invariant
    mask = (turn > TURN_GATE_RPS).astype(np.float64)
    numerator = (lateral * turn * mask).sum(axis=1)
    denominator = (turn * turn * mask).sum(axis=1)
    slope = np.where(denominator > 1e-6, numerator / np.maximum(denominator, 1e-9), 0.0)
    coverage = mask.sum(axis=1) / X.shape[1]
    quality = ((coverage > 0.20) & (slope > 1.0) & (slope < CFG.max_speed_mps)).astype(np.float64)
    return np.clip(slope, 0.0, CFG.max_speed_mps).astype(np.float32), quality.astype(np.float32)

def stack_targets(X, Y):
    cts, quality = turn_targets(X)
    return np.stack([Y, cts, quality], axis=-1).astype(np.float32)


def predict(m, X, batch=512):
    out = m.predict(X, batch_size=batch, verbose=0)
    speed = out[:, 0]
    sigma = np.exp(0.5 * np.clip(out[:, 1], -6.0, 6.0))
    return speed, sigma


def rate_invariance(m, seconds=30.0, base_rate=400.0, rates=(50.0, 100.0, 200.0, 400.0)):
    imu, speed, _ = simulate_run(seconds=seconds, rate_hz=base_rate,
                                 rng=np.random.default_rng(4242))
    rows = []
    for rate in rates:
        low_imu, low_speed = resample(imu, speed, base_rate, rate)          # what the phone records
        grid, grid_speed = resample(low_imu, low_speed, rate, CFG.canonical_rate_hz)
        windows, truth = [], []
        hop = int(CFG.hop_seconds * CFG.canonical_rate_hz)
        for start in range(0, len(grid) - WINDOW, hop):
            windows.append(grid[start:start + WINDOW])
            truth.append(grid_speed[start + WINDOW - 1])
        pred, _ = predict(m, np.asarray(windows, dtype=np.float32))
        rows.append((rate, float(np.mean(pred)), float(np.mean(truth))))
    return rows


def turn_response(m, speed_mps=16.67, rate_hz=200.0, seconds=20.0):
    results = {}
    for omega in (0.0, 0.05, 0.10, 0.20):
        rng = np.random.default_rng(77)
        n = int(seconds * rate_hz); dt = 1.0 / rate_hz
        speed = np.full(n, speed_mps)
        radius = 0.30
        phase = 2 * math.pi * np.cumsum(speed / (2 * math.pi * radius)) * dt
        vib = np.stack([0.35 * np.sin(phase * (k + 1)) for k in range(3)], axis=-1)
        f = np.stack([np.zeros(n), speed * omega, np.full(n, G)], axis=-1) + vib
        w = np.stack([np.zeros(n), np.zeros(n), np.full(n, omega)], axis=-1)
        R = _rotation(1.1, 0.2, -0.15)
        imu = np.concatenate([f @ R.T, w @ R.T], axis=-1).astype(np.float32)
        imu += rng.normal(0, 0.05, imu.shape).astype(np.float32)
        grid, _ = resample(imu, speed, rate_hz, CFG.canonical_rate_hz)
        windows = np.asarray([grid[s:s + WINDOW] for s in
                              range(0, len(grid) - WINDOW, int(CFG.canonical_rate_hz))], dtype=np.float32)
        pred, _ = predict(m, windows)
        results[omega] = float(np.mean(pred))
    return results



"""Train, checkpoint, calibrate, and export the repaired SETU CNN-GRU."""
import gc, hashlib, json, pathlib, platform, shutil, subprocess, time, traceback

OUT = pathlib.Path("setu-speed-v1")
OUT.mkdir(exist_ok=True)
START = time.time()

def save_json(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, allow_nan=False), encoding="utf-8")

def targets_batched(x, y):
    return np.concatenate([stack_targets(x[i:i+2048], y[i:i+2048]) for i in range(0, len(x), 2048)])

def metrics(truth, speed, sigma=None):
    error = speed - truth
    moving = truth > 3
    result = {"windows": len(truth), "mae_mps": float(np.abs(error).mean()),
              "rmse_mps": float(np.sqrt(np.mean(error ** 2))),
              "p90_absolute_error_mps": float(np.percentile(np.abs(error), 90)),
              "bias_mps": float(error.mean()),
              "median_relative_error_moving": float(np.median(np.abs(error[moving]) / truth[moving])) if moving.any() else None}
    if sigma is not None:
        result["coverage"] = {f"{k}_sigma": float(np.mean(np.abs(error) <= k * sigma)) for k in (1, 2, 3)}
        result["mean_sigma_mps"] = float(sigma.mean())
        result["std_sigma_mps"] = float(sigma.std())
    return result

print("Runtime:", tf.__version__, np.__version__, tf.config.list_physical_devices("GPU"), flush=True)
save_json("environment.json", {"python": platform.python_version(), "tensorflow": tf.__version__,
    "numpy": np.__version__, "gpu": [str(x) for x in tf.config.list_physical_devices("GPU")],
    "seed": SEED, "config": dataclasses.asdict(CFG), "batch_normalization_momentum": 0.9})
freeze = subprocess.run([__import__("sys").executable, "-m", "pip", "freeze"], capture_output=True, text=True)
(OUT / "environment-freeze.txt").write_text(freeze.stdout)
data_root = pathlib.Path("/kaggle/temp/setu-data") if pathlib.Path("/kaggle").exists() else pathlib.Path("data")
names, provenance = acquire_data(data_root)
save_json("data_provenance.json", provenance)
runs, rejected = [], []
for name in names:
    try:
        run = load_pair(data_root, name)
        runs.append(run)
        print("INGEST", json.dumps(run["report"]), flush=True)
    except Exception as error:
        rejected.append({"run": name, "reason": str(error)})
        print("REJECTED", name, str(error), flush=True)
save_json("data_audit.json", {"accepted": [r["report"] for r in runs], "rejected": rejected})
by_name = {r["name"]: r for r in runs}
if not {"m", "s1"} <= set(by_name) or len(runs) < 12:
    raise RuntimeError("Required held-out drivers or sufficient training runs missing; no synthetic fallback")
train_runs = [r for r in runs if r["name"].startswith("v")]
test_runs = [r for r in runs if r["name"].startswith("s")]
Xtr, Ytr, Mtr = window_runs(train_runs)
Xb, Yb, Mb = window_runs([by_name["m"]])
boundary = float(np.median([m[1] for m in Mb]))
end_times = np.asarray([m[1] for m in Mb])
vsel, csel = end_times < boundary - 5, end_times > boundary + 5
Xva, Yva = Xb[vsel], Yb[vsel]
Xcal, Ycal = Xb[csel], Yb[csel]
Xte, Yte, Mte = window_runs(test_runs)
del Xb, Yb
assert len(Xva) and len(Xcal) and len(Xte)
save_json("splits.json", {"train_runs": [r["name"] for r in train_runs],
    "validation_driver": "B (M), first time block", "calibration_driver": "B (M), second time block",
    "test_driver": "A", "test_runs": [r["name"] for r in test_runs],
    "validation_calibration_boundary_s": boundary, "guard_band_s": 10,
    "train_windows": len(Xtr), "validation_windows": len(Xva), "calibration_windows": len(Xcal),
    "test_windows": len(Xte), "split_unit": "driver, with separate time blocks inside calibration driver",
    "limitations": "One held-out test driver in the same vehicle/country; not cross-country validation."})
print("WINDOWS", Xtr.shape, Xva.shape, Xcal.shape, Xte.shape, flush=True)
Ttr, Tva = targets_batched(Xtr, Ytr), targets_batched(Xva, Yva)
del runs, by_name, train_runs, test_runs
gc.collect()

model = build_model()
model.summary()

def speed_mae(y_true, y_pred):
    return tf.reduce_mean(tf.abs(y_true[:, 0] - y_pred[:, 0]))

model.compile(optimizer=tf.keras.optimizers.Adam(1e-3, clipnorm=1.), loss=make_loss(), metrics=[speed_mae])
history = model.fit(Xtr, Ttr, validation_data=(Xva, Tva), batch_size=CFG.batch_size,
    epochs=CFG.epochs, shuffle=True, verbose=2, callbacks=[
        tf.keras.callbacks.ModelCheckpoint(str(OUT / "best.weights.h5"), monitor="val_loss", save_best_only=True, save_weights_only=True),
        tf.keras.callbacks.CSVLogger(str(OUT / "training_history.csv")),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", patience=4, factor=.5, min_lr=1e-5, verbose=1),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=9, restore_best_weights=True, verbose=1),
        tf.keras.callbacks.TerminateOnNaN(),
    ])
model.load_weights(OUT / "best.weights.h5")
model.save(OUT / "speed_model.keras")
save_json("training_history.json", {k: [float(v) for v in values] for k, values in history.history.items()})
speed_cal, sigma_cal_raw = predict(model, Xcal)
SIGMA_SCALE = float(np.sqrt(np.mean(((speed_cal - Ycal) / np.maximum(sigma_cal_raw, 1e-6)) ** 2)))
speed_te, sigma_te = predict(model, Xte)
test_metrics = metrics(Yte, speed_te, sigma_te * SIGMA_SCALE)
baseline_metrics = metrics(Yte, np.full_like(Yte, np.median(Ytr)))
save_json("calibration.json", {"sigma_scale": SIGMA_SCALE, "fitted_on": "driver B second time block",
    "test_coverage": test_metrics["coverage"], "gate_g4_pass": test_metrics["coverage"]["3_sigma"] >= .98})
report = {"trained_on": {"source": "IO-VNBD", "real_runs": len({m[0] for m in Mtr}),
    "dataset_accepted_runs": len(names)-len(rejected), "training_windows": len(Xtr), "synthetic_runs": 0},
    "test": test_metrics, "validation_uncalibrated": metrics(Yva, *predict(model, Xva)),
    "constant_training_median_baseline": baseline_metrics,
    "beats_constant_baseline_mae": test_metrics["mae_mps"] < baseline_metrics["mae_mps"],
    "epochs_completed": len(history.history["loss"]), "best_epoch": int(np.argmin(history.history["val_loss"]))+1,
    "training_seconds": time.time()-START, "parameter_count": model.count_params(), "deployment_approved": False,
    "limits": ["Real input is approximately 10 Hz; interpolation to 100 Hz does not restore lost bandwidth.",
        "One held-out driver, same car and country. No phone latency, two-wheeler, or navigation validation.",
        "Wheel labels use a per-run GPS-calibrated radius; this calibrates evaluation labels, not model input."]}
save_json("eval_report.json", report)
print("REAL TEST", json.dumps(report, indent=2), flush=True)
np.savez_compressed(OUT / "heldout_predictions.npz", truth=Yte, speed=speed_te, sigma=sigma_te*SIGMA_SCALE,
    time_s=np.asarray([m[1] for m in Mte]))
sample = Xte[np.linspace(0, len(Xte)-1, min(1000, len(Xte))).astype(int)]
np.savez_compressed(OUT / "verification_windows.npz", imu=sample)

# These are out-of-domain synthetic diagnostics; they are never used for model selection.
try:
    rates = rate_invariance(model)
    means = [r[1] for r in rates]
    turns = turn_response(model)
    report["synthetic_diagnostics"] = {"rates": rates, "turns": turns,
        "rate_spread": (max(means)-min(means))/max(np.mean(means), 1e-6),
        "turn_worst_deviation": max(abs(v/max(turns[0.], 1e-6)-1) for v in turns.values()),
        "note": "Different sampling bandwidth from real 10 Hz training; diagnostic only."}
except Exception:
    report["synthetic_diagnostics_error"] = traceback.format_exc()
save_json("eval_report.json", report)

def lite_predict(blob, x):
    interpreter = tf.lite.Interpreter(model_content=blob, num_threads=1)
    interpreter.allocate_tensors()
    inp, output = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    values = []
    for window in x:
        interpreter.set_tensor(inp["index"], window[None].astype(inp["dtype"]))
        interpreter.invoke()
        values.append(interpreter.get_tensor(output["index"])[0].copy())
    return np.asarray(values)

try:
    # Unroll only the inference clone (25 GRU steps) to avoid TensorList/Flex operators.
    # Training keeps the fused GPU GRU. Both clones use exactly the same learned weights.
    def clone_layer(layer):
        config = layer.get_config()
        if isinstance(layer, tf.keras.layers.GRU):
            config["unroll"] = True
        return layer.__class__.from_config(config)
    # Clone a fresh uncompiled architecture, so the inference clone never attempts
    # to deserialize the training-only custom loss closure.
    uncompiled = build_model()
    export_model = tf.keras.models.clone_model(uncompiled, clone_function=clone_layer)
    export_model.set_weights(model.get_weights())
    np.testing.assert_allclose(export_model(sample[:8], training=False), model(sample[:8], training=False), atol=1e-4)
    @tf.function(input_signature=[tf.TensorSpec([1, WINDOW, 6], tf.float32, name="imu")])
    def serve(x):
        return export_model(x, training=False)
    from tensorflow.python.framework.convert_to_constants import convert_variables_to_constants_v2
    concrete = convert_variables_to_constants_v2(serve.get_concrete_function())
    converter = tf.lite.TFLiteConverter.from_concrete_functions([concrete])
    float_blob = converter.convert()
    (OUT / "speed_float.tflite").write_bytes(float_blob)
    converter = tf.lite.TFLiteConverter.from_concrete_functions([concrete])
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    # Keep feature denominators and activations in float. Full activation quantization
    # rounds small gravity-feature denominators to zero and crashes the DIV operator.
    # No representative dataset means dynamic-range weight quantization.
    quant_blob = converter.convert()
    (OUT / "speed_int8.tflite").write_bytes(quant_blob)
    float_out = lite_predict(float_blob, sample)
    quant_out = lite_predict(quant_blob, sample)
    keras_out = model.predict(sample, batch_size=256, verbose=0)
    delta = np.abs(quant_out[:, 0]-float_out[:, 0])
    bias = float(np.mean(quant_out[:, 0]-float_out[:, 0]))
    interpreter = tf.lite.Interpreter(model_content=quant_blob, num_threads=1)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    interpreter.set_tensor(inp["index"], sample[:1])
    for _ in range(20):
        interpreter.invoke()
    then = time.perf_counter()
    for _ in range(200):
        interpreter.invoke()
    report["export"] = {"float_bytes": len(float_blob), "int8_bytes": len(quant_blob),
        "keras_float_max_speed_difference_mps": float(np.max(np.abs(keras_out[:, 0]-float_out[:, 0]))),
        "int8_parity_mean_mps": float(delta.mean()), "int8_parity_max_mps": float(delta.max()),
        "int8_parity_p99_mps": float(np.percentile(delta, 99)), "int8_bias_mps": bias,
        "notebook_parity_pass": bool(delta.max() < .25 and abs(bias) < .05),
        "project_parity_pass": bool(delta.mean() < .02 and np.percentile(delta, 99) < .10),
        "kaggle_cpu_single_thread_latency_ms": (time.perf_counter()-then)/200*1000,
        "quantisation": "dynamic-range int8 weights; float activations and float32 input/output"}
    np.savez_compressed(OUT / "export_parity.npz", keras=keras_out, float_tflite=float_out, int8_tflite=quant_out)
except Exception:
    report["export_error"] = traceback.format_exc()
    print(report["export_error"], flush=True)
save_json("eval_report.json", report)

input_spec = {"channels": ["accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"],
    "frame": "phone_body", "units": {"accel": "m/s^2 including gravity", "gyro": "rad/s"},
    "window_samples": WINDOW, "canonical_rate_hz": CFG.canonical_rate_hz, "window_seconds": 4.,
    "conditioning": "Linear timestamp interpolation before model; PhysicalFeatures with exact first-sample EMA seed inside graph.",
    "validated_source_rate_hz": 10., "outputs": ["nonnegative_speed_mps", "log_variance_clipped_to_minus6_plus6_for_sigma"]}
manifest = {"schema": "setu.model-bundle.v1", "version": "speed-real-20260914",
    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "capabilities": ["speed"],
    "vehicles": ["Car"], "tier_min": "C", "input_spec": input_spec,
    "input_spec_sha256": hashlib.sha256(json.dumps(input_spec, sort_keys=True).encode()).hexdigest(),
    "sigma_scale": SIGMA_SCALE, "deployment_approved": False, "evaluation": report,
    "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name != "manifest.json"}}
save_json("manifest.json", manifest)
archive = shutil.make_archive("setu-speed-v1", "zip", OUT)
print("FINISHED", archive, json.dumps(report, indent=2), flush=True)
