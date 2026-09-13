"""Build a reproducible training copy from the user's original notebook."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
notebook = json.loads((ROOT / "setu_speed_model.ipynb").read_text(encoding="utf-8"))


def source(index):
    return "".join(notebook["cells"][index]["source"])


header = '''import dataclasses, math, os, random
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_GPU_ALLOCATOR", "cuda_malloc_async")
import numpy as np
import tensorflow as tf
SEED = 20260912
tf.keras.utils.set_random_seed(SEED)
for device in tf.config.list_physical_devices("GPU"):
    tf.config.experimental.set_memory_growth(device, True)
'''
config = source(5).replace("hop_seconds: float = 0.25", "hop_seconds: float = 1.0")
config = config.replace("min_rate_hz: float = 25.0", "min_rate_hz: float = 10.0")
physics = source(13)
physics = '@tf.keras.utils.register_keras_serializable(package="SETU")\n' + physics
start = physics.index("        # Seed the filter")
end = physics.index("\n        down =", start)
physics = physics[:start] + '''        # Exact EMA seed: a constant input remains constant from the first sample.
        # The original blend decayed toward zero and used future window samples.
        gravity += accel[:, :1, :] * decay * (1.0 - self.alpha)
''' + physics[end:]
model = source(14).split("\nmodel = build_model()")[0]
model = model.replace("tf.keras.layers.BatchNormalization()", "tf.keras.layers.BatchNormalization(momentum=0.9)")
model = model.replace('tf.keras.layers.Activation(lambda v: tf.nn.softplus(v), name="speed")',
                      'tf.keras.layers.Activation("softplus", name="speed")')
loss = source(16).split("\nTtr, Tva, Tte =")[0]
resample = source(11).split("\ndef make_windows")[0]
predict = source(19).split("\nspeed_te, sigma_te =")[0]
rate_probe = source(23).split("\nrows = rate_invariance")[0]
turn_probe = source(25).split("\nturns = turn_response")[0]
simulator = source(9).split("\n# A spread of source rates")[0]
model_source = "\n\n".join([header, config, simulator, resample, physics, model, loss, predict, rate_probe, turn_probe]) + "\n"
(ROOT / "setu_model.py").write_text(model_source, encoding="utf-8")

training = (ROOT / "training_run.py").read_text(encoding="utf-8")
combined = (ROOT / "training_data.py").read_text(encoding="utf-8") + "\n\n" + model_source + "\n\n" + training
combined = combined.replace("from training_data import acquire_data, load_pair, window_runs\n", "")
combined = combined.replace("from setu_model import *\n", "")
(ROOT / "kaggle_train.py").write_text(combined, encoding="utf-8")
cells = [
    {"cell_type": "markdown", "id": "overview", "metadata": {}, "source": [
        "# SETU speed model: real IO-VNBD training\n",
        "Generated from setu_speed_model.ipynb. Preserves its CNN-GRU and loss; repairs ingestion, EMA initialization, serialization, checkpointing, and export.\n",
        "All measurements are research results. Driver E is training-only, driver B is split into disjoint validation/calibration time blocks, and driver A is test-only.\n"]},
    {"cell_type": "code", "id": "training", "metadata": {}, "execution_count": None, "outputs": [], "source": combined.splitlines(keepends=True)},
]
output = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}
(ROOT / "setu_speed_model_training.ipynb").write_text(json.dumps(output, indent=1), encoding="utf-8")
print("Built setu_model.py, kaggle_train.py, and setu_speed_model_training.ipynb")
