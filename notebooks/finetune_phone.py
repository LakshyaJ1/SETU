"""Fine-tune an existing speed checkpoint on explicitly split Android recordings.

Produces a research candidate only; never changes the Android model bundle.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def load_dataset(directory, minimum_windows=100):
    directory = Path(directory)
    report = json.loads((directory / "dataset.json").read_text(encoding="utf-8"))
    vehicle = report.get("vehicle", "Car")
    if (
        report.get("schema") != "setu.phone-dataset.v1"
        or report.get("windowSamples") != 400
        or report.get("canonicalRateHz") != 100
        or report.get("channels") != ["accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"]
        or vehicle not in ("Car", "Two-wheeler")
    ):
        raise ValueError("Incompatible phone dataset")
    grouped = {name: [] for name in ("train", "validation", "calibration", "test")}
    seen, assignments = set(), {}
    for session in report["sessions"]:
        if session.get("diagnosticOnly"):
            raise ValueError("Diagnostic cohort cannot enter the production fine-tuning pipeline")
        if session.get("vehicle", "Car") != vehicle or session.get("mount", "fixed") != "fixed":
            raise ValueError("Dataset mixes vehicles or contains an unconfirmed mount")
        split = session["split"]
        identity = session["sessionId"]
        if identity in seen or session["sourceSha256"] in seen:
            raise ValueError("Duplicate session")
        seen.update((identity, session["sourceSha256"]))
        for key in (
            ("group", session["group"]),
            ("device-day", session["installationId"], session["utcDay"]),
        ):
            if assignments.setdefault(key, split) != split:
                raise ValueError("Split leakage")
        file = (directory / session["file"]).resolve()
        if (
            file.parent != directory.resolve()
            or hashlib.sha256(file.read_bytes()).hexdigest() != session["sha256"]
        ):
            raise ValueError("Dataset shard integrity mismatch")
        with np.load(file, allow_pickle=False) as data:
            features, labels = data["imu"], data["speed_mps"]
            if (
                features.shape != (len(labels), 400, 6)
                or not np.isfinite(features).all()
                or not np.isfinite(labels).all()
                or np.any(labels < 0)
                or np.any(labels > 45)
            ):
                raise ValueError("Invalid training tensors")
            grouped[split].append((features, labels))
    result = {}
    for split, shards in grouped.items():
        if sum(len(labels) for _, labels in shards) < minimum_windows:
            raise ValueError(f"Need at least {minimum_windows} quality windows in {split}")
        result[split] = (
            np.concatenate([features for features, _ in shards]),
            np.concatenate([labels for _, labels in shards]),
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--checkpoint", type=Path, help="Existing compatible .weights.h5 file")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--check-only", action="store_true")
    arguments = parser.parse_args()
    dataset = load_dataset(arguments.dataset)
    if arguments.check_only:
        print(json.dumps({split: len(labels) for split, (_, labels) in dataset.items()}, indent=2))
        return
    if not arguments.checkpoint or not arguments.checkpoint.is_file() or not arguments.output:
        parser.error("Training requires --checkpoint and a new --output directory")
    if not 1 <= arguments.epochs <= 40:
        parser.error("--epochs must be between 1 and 40")

    import tensorflow as tf
    from setu_model import build_model, make_loss

    arguments.output.mkdir(parents=True, exist_ok=False)
    tf.keras.utils.set_random_seed(20260914)
    model = build_model()
    model.load_weights(arguments.checkpoint)
    for layer in model.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
    test_features, test_labels = dataset["test"]
    baseline = model.predict(test_features, verbose=0)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5), loss=make_loss(physics_weight=0.0)
    )

    def targets(labels):
        return np.stack([labels, np.zeros_like(labels), np.zeros_like(labels)], axis=1)

    train_features, train_labels = dataset["train"]
    validation_features, validation_labels = dataset["validation"]
    history = model.fit(
        train_features,
        targets(train_labels),
        batch_size=64,
        validation_data=(validation_features, targets(validation_labels)),
        epochs=arguments.epochs,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=3, restore_best_weights=True
            )
        ],
    )
    calibration_features, calibration_labels = dataset["calibration"]
    calibration = model.predict(calibration_features, verbose=0)
    calibration_sigma = np.exp(0.5 * np.clip(calibration[:, 1], -6, 6))
    scale = float(
        max(
            1.0,
            np.quantile(np.abs(calibration[:, 0] - calibration_labels) / calibration_sigma, 0.98)
            / 3,
        )
    )
    prediction = model.predict(test_features, verbose=0)
    if not all(np.isfinite(values).all() for values in (baseline, calibration, prediction)):
        raise ValueError("Non-finite model predictions; candidate is not saved")
    error = np.abs(prediction[:, 0] - test_labels)
    sigma = scale * np.exp(0.5 * np.clip(prediction[:, 1], -6, 6))
    model.save_weights(arguments.output / "candidate.weights.h5")
    model.save(arguments.output / "candidate.keras")
    report = {
        "deployment_approved": False,
        "vehicle": json.loads((arguments.dataset / "dataset.json").read_text(encoding="utf-8"))
        .get("vehicle", "Car"),
        "label_reference": "Android GNSS speed, not independent ground truth",
        "test_mae_mps": float(error.mean()),
        "test_p95_mps": float(np.quantile(error, 0.95)),
        "baseline_test_mae_mps": float(np.abs(baseline[:, 0] - test_labels).mean()),
        "test_3sigma_coverage": float(np.mean(error <= 3 * sigma)),
        "sigma_scale": scale,
        "dataset_manifest_sha256": hashlib.sha256(
            (arguments.dataset / "dataset.json").read_bytes()
        ).hexdigest(),
        "checkpoint_sha256": hashlib.sha256(arguments.checkpoint.read_bytes()).hexdigest(),
        "tensorflow_version": tf.__version__,
        "epochs": len(history.history["loss"]),
        "required_before_deployment": [
            "held-out phones/vehicles/routes",
            "GPS-withheld trajectory trials",
            "TFLite parity and phone latency",
            "calibrated uncertainty and deployment review",
        ],
    }
    (arguments.output / "evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (arguments.output / "history.json").write_text(
        json.dumps(history.history, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
