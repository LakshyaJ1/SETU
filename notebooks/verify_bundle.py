"""Verify downloaded model integrity and replay its inference locally."""
import hashlib
import json
from pathlib import Path

import numpy as np
import setu_model as sm

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "setu-speed-v1"
manifest = json.loads((BUNDLE / "manifest.json").read_text())
for name, expected in manifest["files"].items():
    path = (BUNDLE / name).resolve()
    if not path.is_relative_to(BUNDLE) or not path.is_file():
        raise ValueError(f"Missing/invalid artifact: {name}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Hash mismatch: {name}")
spec_hash = hashlib.sha256(json.dumps(manifest["input_spec"], sort_keys=True).encode()).hexdigest()
assert spec_hash == manifest["input_spec_sha256"]
saved = np.load(BUNDLE / "heldout_predictions.npz")
truth, speed, sigma = saved["truth"], saved["speed"], saved["sigma"]
assert len(truth) > 0 and np.all(np.isfinite(speed)) and np.all(np.isfinite(sigma)) and np.all(sigma > 0)
mae = float(np.abs(speed-truth).mean())
rmse = float(np.sqrt(np.mean((speed-truth)**2)))
np.testing.assert_allclose(mae, manifest["evaluation"]["test"]["mae_mps"], atol=1e-6)
np.testing.assert_allclose(rmse, manifest["evaluation"]["test"]["rmse_mps"], atol=1e-6)
windows = np.load(BUNDLE / "verification_windows.npz")["imu"]
model = sm.tf.keras.models.load_model(BUNDLE / "speed_model.keras", compile=False)
out = model(windows[:32], training=False).numpy()
assert out.shape == (min(32, len(windows)), 2) and np.all(np.isfinite(out))
result = {"integrity": "pass", "files_verified": len(manifest["files"]), "keras_load_and_inference": "pass",
          "heldout_metric_recalculation": "pass", "test_mae_mps": mae, "test_rmse_mps": rmse,
          "local_tensorflow": sm.tf.__version__, "local_numpy": np.__version__}
indices = np.linspace(0, len(truth)-1, len(windows)).astype(int)[:len(out)]
np.testing.assert_allclose(out[:,0], speed[indices], atol=1e-3, rtol=1e-4)
local_sigma = np.exp(.5*np.clip(out[:,1], -6, 6))*manifest["sigma_scale"]
np.testing.assert_allclose(local_sigma, sigma[indices], atol=1e-3, rtol=1e-4)
result["keras_local_vs_kaggle_max_speed_difference_mps"] = float(np.max(np.abs(out[:,0]-speed[indices])))
result["keras_local_vs_kaggle_max_sigma_difference_mps"] = float(np.max(np.abs(local_sigma-sigma[indices])))
parity_file = BUNDLE / "export_parity.npz"
if parity_file.exists():
    expected = np.load(parity_file)
    result["keras_local_vs_export_reference_max_difference"] = float(np.max(np.abs(out-expected["keras"][:len(out)])))
    np.testing.assert_allclose(out, expected["keras"][:len(out)], atol=1e-3, rtol=1e-4)
for name in ("speed_float.tflite", "speed_int8.tflite"):
    path = BUNDLE / name
    if not path.exists():
        result[name] = "not exported"
        continue
    interpreter = sm.tf.lite.Interpreter(model_path=str(path), num_threads=1)
    interpreter.allocate_tensors()
    inp, output = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    values = []
    for x in windows[:32]:
        interpreter.set_tensor(inp["index"], x[None].astype(inp["dtype"]))
        interpreter.invoke()
        values.append(interpreter.get_tensor(output["index"])[0].copy())
    values = np.asarray(values)
    assert np.all(np.isfinite(values))
    result[name] = {"load_and_inference": "pass", "shape": list(values.shape)}
    if parity_file.exists():
        key = "int8_tflite" if "int8" in name else "float_tflite"
        np.testing.assert_allclose(values, expected[key][:len(values)], atol=1e-3, rtol=1e-4)
        result[name]["local_vs_export_reference_max_difference"] = float(np.max(np.abs(values-expected[key][:len(values)])))
(ROOT / "local_verification.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
