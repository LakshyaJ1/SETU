import pathlib, zipfile
import numpy as np
import setu_model as sm

root = pathlib.Path(__file__).resolve().parent
destination = (root / "baseline-v3").resolve()
destination.mkdir(exist_ok=True)
with zipfile.ZipFile(root / "baseline-v3.zip") as archive:
    for member in archive.infolist():
        if not (destination / member.filename).resolve().is_relative_to(destination):
            raise ValueError("Unsafe archive path")
    archive.extractall(destination)
model = sm.tf.keras.models.load_model(destination / "speed_model.keras", compile=False)
x = np.load(destination / "verification_windows.npz")["imu"][:128]
for training in (False, True):
    out = model(x, training=training).numpy()
    print("training_mode", training, "speed_mean", out[:,0].mean(), "speed_std", out[:,0].std(),
          "speed_min_max", out[:,0].min(), out[:,0].max(), "log_var_std", out[:,1].std(), flush=True)
for layer in model.layers:
    if isinstance(layer, sm.tf.keras.layers.BatchNormalization):
        print(layer.name, "moving_variance_range", layer.moving_variance.numpy().min(), layer.moving_variance.numpy().max(), flush=True)
