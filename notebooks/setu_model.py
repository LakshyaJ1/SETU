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

