"""Create a concise results record from saved evidence, without model selection."""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "setu-speed-v1"
report = json.loads((BUNDLE / "eval_report.json").read_text())
split = json.loads((BUNDLE / "splits.json").read_text())
audit = json.loads((BUNDLE / "data_audit.json").read_text())
pred = np.load(BUNDLE / "heldout_predictions.npz")
truth, speed, sigma, seconds = (pred[k] for k in ("truth", "speed", "sigma", "time_s"))

def measure(mask):
    error = speed[mask]-truth[mask]
    return {"windows": int(mask.sum()), "mae_mps": float(np.abs(error).mean()),
            "rmse_mps": float(np.sqrt(np.mean(error**2))), "bias_mps": float(error.mean()),
            "three_sigma_coverage": float(np.mean(np.abs(error) <= 3*sigma[mask]))}

starts = np.r_[0, np.flatnonzero(np.diff(seconds) <= 0)+1]
stops = np.r_[starts[1:], len(seconds)]
assert len(starts) == len(split["test_runs"])
by_run = {name: measure((np.arange(len(speed)) >= start) & (np.arange(len(speed)) < stop))
          for name,start,stop in zip(split["test_runs"], starts, stops)}
bands = {}
for name, low, high in (("0_to_1_mps", 0,1), ("1_to_5_mps",1,5), ("5_to_15_mps",5,15), ("15_plus_mps",15,100)):
    take = (truth >= low) & (truth < high)
    if take.any():
        bands[name] = measure(take)
diagnostics = {"per_test_run": by_run, "speed_bands": bands,
    "prediction_std_mps": float(speed.std()), "reference_std_mps": float(truth.std()),
    "accepted_data_runs": len(audit["accepted"]), "rejected_data_runs": len(audit["rejected"])}
(ROOT / "evaluation_breakdown.json").write_text(json.dumps(diagnostics, indent=2))
test, baseline = report["test"], report["constant_training_median_baseline"]
improvement = 100*(1-test["mae_mps"]/baseline["mae_mps"])
text = f"""# SETU training result

Training completed on a private Kaggle GPU using {len(split['train_runs'])} real IO-VNBD recordings ({split['train_windows']:,} windows). No synthetic data was used for training. Early stopping completed {report['epochs_completed']} epochs and selected epoch {report['best_epoch']} by validation loss. The model contains {report['parameter_count']:,} parameters.

The final test contains {split['test_windows']:,} windows from four recordings by held-out driver A. Mean absolute speed error is {test['mae_mps']:.4f} m/s ({test['mae_mps']*3.6:.2f} km/h), and RMSE is {test['rmse_mps']:.4f} m/s. A constant training-median baseline has MAE {baseline['mae_mps']:.4f} m/s; the learned model changes MAE by {improvement:+.1f}% relative to that baseline (positive means improvement). Prediction standard deviation is {speed.std():.4f} m/s. Calibration was fitted on a separate block from driver B; test three-sigma coverage is {test['coverage']['3_sigma']*100:.2f}%.

The model is saved in `setu-speed-v1/speed_model.keras`, with weights, calibration, split metadata, source-file hashes, and evaluation evidence. `setu-speed-v1.zip` contains the bundle. `local_verification.json` records local integrity and inference checks. `training_results.png` plots the recorded learning curve, predictions, and coverage; `evaluation_breakdown.json` gives per-run and speed-band errors.

The original notebook is preserved. Reproduction starts from `setu_speed_model_training.ipynb` or `kaggle_train.py`; see `TRAINING.md`. The private run is https://www.kaggle.com/code/psychoxd12/setu-speed-real-training-20260914.

These are research results on quality-filtered 10 Hz data from one vehicle/country. The rejected data and residual alignment limitations remain documented in `data_audit.json`. Phone latency, other vehicles, two-wheelers, and navigation accuracy have not been validated. Deployment approval remains false in the manifest.
"""
if "export" in report:
    export = report["export"]
    text += f"\nTFLite float and mixed-int8 exports were produced. Quantized versus float speed error is {export['int8_parity_mean_mps']:.5f} m/s on average and {export['int8_parity_max_mps']:.5f} m/s at worst. Notebook parity gate: {export['notebook_parity_pass']}; stricter project parity gate: {export['project_parity_pass']}.\n"
else:
    text += "\nTFLite export did not complete; inspect the recorded export error. The trained Keras checkpoint remains available.\n"
(ROOT / "TRAINING_RESULTS.md").write_text(text, encoding="utf-8")
print(json.dumps(diagnostics, indent=2))
