"""Export the saved checkpoint with int8 weights and float activations; no training."""
import hashlib, json, pathlib, platform, shutil, time
import numpy as np
import setu_model as sm

ROOT = pathlib.Path(__file__).resolve().parent
BUNDLE = ROOT / "setu-speed-v1"
checkpoint_hash = hashlib.sha256((BUNDLE / "speed_model.keras").read_bytes()).hexdigest()
manifest = json.loads((BUNDLE / "manifest.json").read_text())
for name, expected in manifest["files"].items():
    assert hashlib.sha256((BUNDLE/name).read_bytes()).hexdigest() == expected, name
model = sm.tf.keras.models.load_model(BUNDLE / "speed_model.keras", compile=False)

def clone_layer(layer):
    config = layer.get_config()
    if isinstance(layer, sm.tf.keras.layers.GRU):
        config["unroll"] = True
    return layer.__class__.from_config(config)

export_model = sm.tf.keras.models.clone_model(model, clone_function=clone_layer)
export_model.set_weights(model.get_weights())
sample = np.load(BUNDLE / "verification_windows.npz")["imu"]
np.testing.assert_allclose(export_model(sample[:8], training=False), model(sample[:8], training=False), atol=1e-4)

@sm.tf.function(input_signature=[sm.tf.TensorSpec([1,400,6], sm.tf.float32, name="imu")])
def serve(x):
    return export_model(x, training=False)

from tensorflow.python.framework.convert_to_constants import convert_variables_to_constants_v2
frozen = convert_variables_to_constants_v2(serve.get_concrete_function())
np.testing.assert_allclose(frozen(sm.tf.constant(sample[:1]))[0], model(sample[:1], training=False), atol=1e-4)
converter = sm.tf.lite.TFLiteConverter.from_concrete_functions([frozen])
converter.optimizations = [sm.tf.lite.Optimize.DEFAULT]
# Dynamic-range quantization leaves feature denominators and activations floating point.
# Full activation quantization rounded the gravity feature's small denominator to zero.
blob = converter.convert()
(BUNDLE / "speed_int8.tflite").write_bytes(blob)

def run(path):
    interpreter = sm.tf.lite.Interpreter(model_path=str(path), num_threads=1)
    interpreter.allocate_tensors()
    inp, output = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    result = []
    for x in sample:
        interpreter.set_tensor(inp["index"], x[None].astype(inp["dtype"]))
        interpreter.invoke()
        result.append(interpreter.get_tensor(output["index"])[0].copy())
    values = np.asarray(result)
    assert np.all(np.isfinite(values)), "Non-finite inference result"
    return values, interpreter

float_out, _ = run(BUNDLE / "speed_float.tflite")
quant_out, interpreter = run(BUNDLE / "speed_int8.tflite")
keras_out = model.predict(sample, batch_size=128, verbose=0)
delta = np.abs(quant_out[:,0]-float_out[:,0])
bias = float(np.mean(quant_out[:,0]-float_out[:,0]))
for _ in range(20):
    interpreter.invoke()
then = time.perf_counter()
for _ in range(200):
    interpreter.invoke()
latency = (time.perf_counter()-then)/200*1000
quantized_tensors = sum(x["dtype"] == np.int8 for x in interpreter.get_tensor_details())
assert quantized_tensors > 0, "Converter did not produce int8 weights"
report = json.loads((BUNDLE / "eval_report.json").read_text())
if "export_error" in report:
    report["previous_export_error"] = report.pop("export_error")
report["export"] = {"float_bytes": (BUNDLE/"speed_float.tflite").stat().st_size, "int8_bytes": len(blob),
    "keras_float_max_speed_difference_mps": float(np.max(np.abs(keras_out[:,0]-float_out[:,0]))),
    "int8_parity_mean_mps": float(delta.mean()), "int8_parity_max_mps": float(delta.max()),
    "int8_parity_p99_mps": float(np.percentile(delta,99)), "int8_bias_mps": bias,
    "int8_log_variance_max_difference": float(np.max(np.abs(quant_out[:,1]-float_out[:,1]))),
    "notebook_parity_pass": bool(delta.max() < .25 and abs(bias) < .05),
    "project_parity_pass": bool(delta.mean() < .02 and np.percentile(delta,99) < .10),
    "local_cpu_single_thread_latency_ms": latency, "quantized_tensor_count": quantized_tensors,
    "quantisation": "dynamic-range int8 weights; float activations, feature preprocessing, input and output",
    "runtime": {"tensorflow": sm.tf.__version__, "numpy": np.__version__, "python": platform.python_version()},
    "source_checkpoint_sha256": checkpoint_hash, "retrained": False}
assert hashlib.sha256((BUNDLE/"speed_model.keras").read_bytes()).hexdigest() == checkpoint_hash
np.savez_compressed(BUNDLE / "export_parity.npz", keras=keras_out, float_tflite=float_out, int8_tflite=quant_out)
(BUNDLE/"eval_report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
manifest["evaluation"] = report
manifest["quantisation"] = report["export"]["quantisation"]
manifest["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in BUNDLE.iterdir() if p.is_file() and p.name != "manifest.json"}
(BUNDLE/"manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False))
archive = shutil.make_archive(str(ROOT / "setu-speed-v1"), "zip", BUNDLE)
print(json.dumps(report["export"], indent=2), flush=True)
print("EXPORTED", archive, flush=True)
