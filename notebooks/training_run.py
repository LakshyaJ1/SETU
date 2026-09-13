"""Train, checkpoint, calibrate, and export the repaired SETU CNN-GRU."""
import gc, hashlib, json, pathlib, platform, shutil, subprocess, time, traceback
from training_data import acquire_data, load_pair, window_runs
from setu_model import *

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
