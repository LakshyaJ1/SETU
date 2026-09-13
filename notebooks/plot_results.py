"""Plot the recorded training history and held-out evaluation, without retraining."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "setu-speed-v1"
history = json.loads((BUNDLE / "training_history.json").read_text())
report = json.loads((BUNDLE / "eval_report.json").read_text())
pred = np.load(BUNDLE / "heldout_predictions.npz")
truth, speed, sigma, seconds = (pred[key] for key in ("truth", "speed", "sigma", "time_s"))
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.alpha": .2})
fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
epochs = np.arange(1, len(history["loss"])+1)
axes[0,0].plot(epochs, history["loss"], label="Training", color="#2065a2")
axes[0,0].plot(epochs, history["val_loss"], label="Validation: driver B", color="#d26932")
axes[0,0].axvline(report["best_epoch"], color="#444444", linestyle="--", label="Selected checkpoint")
axes[0,0].set(xlabel="Epoch", ylabel="Combined training objective", title="Checkpoint selection")
axes[0,0].legend(frameon=False)
step = max(1, len(truth)//1600)
axes[0,1].scatter(truth[::step], speed[::step], s=5, alpha=.35, color="#2065a2")
limit = float(max(truth.max(), speed.max()))
axes[0,1].plot([0,limit], [0,limit], color="#444444", linestyle="--")
axes[0,1].set(xlabel="Wheel-reference speed (m/s)", ylabel="Predicted speed (m/s)", title="Held-out driver A")
# Show one ten-minute interval without drawing lines across recording gaps.
resets = np.flatnonzero(np.diff(seconds) <= 0)
first_run_end = int(resets[0]+1) if len(resets) else len(seconds)
view = (seconds <= seconds[0]+600) & (np.arange(len(seconds)) < first_run_end)
t = seconds[view]/60
gap = np.r_[False, np.diff(t) > 1.5/60]
shown_truth, shown_speed, shown_sigma = truth[view].copy(), speed[view].copy(), sigma[view].copy()
shown_truth[gap] = np.nan
shown_speed[gap] = np.nan
shown_sigma[gap] = np.nan
axes[1,0].plot(t, shown_truth, label="Wheel reference", color="#444444", lw=1.2)
axes[1,0].plot(t, shown_speed, label="Prediction", color="#2065a2", lw=1)
axes[1,0].fill_between(t, np.maximum(0,shown_speed-shown_sigma), shown_speed+shown_sigma, color="#2065a2", alpha=.15, label="Predicted ±1 sigma")
axes[1,0].set(xlabel="Recording time (minutes)", ylabel="Speed (m/s)", title="First ten minutes of test windows")
axes[1,0].legend(frameon=False, fontsize=8)
actual = [np.mean(np.abs(speed-truth) <= k*sigma)*100 for k in (1,2,3)]
axes[1,1].bar([1,2,3], actual, color="#2065a2", width=.55)
axes[1,1].plot([1,2,3], [68.27,95.45,99.73], "o--", color="#d26932", label="Gaussian reference")
axes[1,1].axhline(98, color="#777777", linestyle=":", label="3-sigma gate: 98%")
axes[1,1].set(xticks=[1,2,3], xticklabels=["±1 sigma", "±2 sigma", "±3 sigma"], ylim=(0,103), ylabel="Observed coverage (%)", title="Calibration on held-out test windows")
axes[1,1].legend(loc="lower right", frameon=True, facecolor="white", framealpha=.95, fontsize=8)
test = report["test"]
fig.suptitle(f"SETU real-data training | Test MAE {test['mae_mps']:.2f} m/s | RMSE {test['rmse_mps']:.2f} m/s\nResearch evaluation: one held-out driver; no phone or navigation certification", fontsize=13)
fig.savefig(ROOT / "training_results.png", dpi=160)
print(ROOT / "training_results.png")
