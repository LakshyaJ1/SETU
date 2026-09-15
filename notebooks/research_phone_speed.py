"""Time-capped, whole-ride-held-out CPU experiment; never promotes an Android model."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from setu.collection import convert_bundle


def metrics(truth, prediction):
    truth = np.asarray(truth)
    prediction = np.asarray(prediction)
    if truth.shape != prediction.shape or not len(truth) or not np.isfinite(prediction).all():
        raise ValueError("Invalid evaluation arrays")
    error = np.abs(truth - prediction)
    return {
        "windows": len(truth), "maeMps": float(error.mean()),
        "rmseMps": float(np.sqrt(np.mean(error ** 2))),
        "absoluteErrorP90Mps": float(np.quantile(error, .9)),
        "within1Mps": float(np.mean(error <= 1)),
        "stationaryWindows": int(np.sum(truth <= .5)),
        "stationaryPredictedSpeedP90Mps": (
            float(np.quantile(prediction[truth <= .5], .9)) if np.any(truth <= .5) else None
        ),
    }


def fold_indices(count, held_out):
    if count < 3 or held_out not in range(count):
        raise ValueError("Need at least three distinct rides and a valid held-out index")
    return [index for index in range(count) if index != held_out], held_out


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", type=Path, nargs=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--fit-all", action="store_true")
    arguments = parser.parse_args()
    if not 1 <= arguments.minutes <= 25 or not 1 <= arguments.epochs <= 40:
        parser.error("Budget must be 1–25 minutes and epochs 1–40")
    if not 1 <= arguments.threads <= 8:
        parser.error("Use 1–8 CPU threads")
    arguments.output.mkdir(parents=True, exist_ok=False)
    deadline = started + arguments.minutes * 60
    report = {
        "schema": "setu.phone-speed-research.v1", "deploymentApproved": False,
        "vehicle": "Two-wheeler", "diagnosticOnly": True,
        "labelReference": "Quality-filtered phone GNSS speed, not independent ground truth",
        "split": "Leave one entire ride out; same phone/day cohort, not independent validation",
        "fixedEpochs": arguments.epochs, "budgetSeconds": arguments.minutes * 60,
        "initialization": "Random weights; this is training, not fine-tuning a pretrained model",
        "sessions": [], "folds": [], "status": "loading",
        "requiredBeforeDeployment": [
            "Independent days, routes, phones and vehicle/mount validation",
            "Separate uncertainty calibration; quantization parity and phone latency",
            "GPS-withheld trajectory accuracy and stationary false-speed checks",
        ],
    }

    def save():
        report["elapsedSeconds"] = time.monotonic() - started
        staging = arguments.output / "report.pending"
        staging.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        staging.replace(arguments.output / "report.json")

    sessions = []
    identities = set()
    for path in arguments.bundles:
        tensors, metadata = convert_bundle(path, vehicle="Two-wheeler", diagnostic=True)
        if (metadata["sourceSha256"] in identities or metadata["sessionId"] in identities
                or metadata["acceptedWindows"] < 100):
            raise ValueError("Need three unique rides with at least 100 quality windows each")
        identities.update((metadata["sourceSha256"], metadata["sessionId"]))
        sessions.append((tensors["imu"], tensors["speed_mps"]))
        report["sessions"].append(metadata)
        save()
        print(f"Loaded ride {len(sessions)}: {metadata['acceptedWindows']} windows", flush=True)

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    import tensorflow as tf
    tf.config.threading.set_intra_op_parallelism_threads(arguments.threads)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    from notebooks.setu_model import build_model, make_loss

    class Budget(tf.keras.callbacks.Callback):
        def on_train_batch_end(self, batch, logs=None):
            if time.monotonic() >= deadline - 45:
                self.model.stop_training = True

    report["tensorflowVersion"] = tf.__version__
    report["hardware"] = "CPU"
    report["status"] = "training"
    save()

    def train(features, labels, tag, seed):
        tf.keras.backend.clear_session()
        tf.keras.utils.set_random_seed(seed)
        model = build_model()
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=.001),
                      loss=make_loss(physics_weight=0.0))
        targets = np.stack([labels, np.zeros_like(labels), np.zeros_like(labels)], axis=1)
        epoch_seconds = []
        completed_epochs = 0
        for epoch in range(arguments.epochs):
            if time.monotonic() >= deadline - 60:
                break
            epoch_started = time.monotonic()
            model.fit(features, targets, batch_size=64, epochs=1, verbose=0, callbacks=[Budget()])
            epoch_seconds.append(time.monotonic() - epoch_started)
            if not model.stop_training:
                completed_epochs += 1
            print(f"{tag}, epoch {epoch + 1}: {epoch_seconds[-1]:.1f}s", flush=True)
            if model.stop_training:
                break
        return model, completed_epochs, epoch_seconds

    for held_out in range(len(sessions)):
        if time.monotonic() >= deadline - 60:
            break
        train_indices, test_index = fold_indices(len(sessions), held_out)
        train_features = np.concatenate([sessions[index][0] for index in train_indices])
        train_labels = np.concatenate([sessions[index][1] for index in train_indices])
        test_features, test_labels = sessions[test_index]
        model, completed_epochs, epoch_seconds = train(
            train_features, train_labels, f"Fold {held_out + 1}", 20260915 + held_out
        )
        prediction = model.predict(test_features, batch_size=64, verbose=0)
        checkpoint = arguments.output / f"fold-{held_out + 1}.weights.h5"
        model.save_weights(checkpoint)
        np.savez_compressed(arguments.output / f"fold-{held_out + 1}-predictions.npz",
                            truth=test_labels, prediction=prediction)
        fold = {
            "heldOutSessionId": report["sessions"][test_index]["sessionId"],
            "trainSessionIds": [report["sessions"][index]["sessionId"] for index in train_indices],
            "trainWindows": len(train_labels), "completedEpochs": completed_epochs,
            "epochSeconds": epoch_seconds, "trainingStoppedForBudget": bool(model.stop_training),
            "model": metrics(test_labels, prediction[:, 0]),
            "trainMedianBaseline": metrics(test_labels, np.full_like(test_labels,
                                                                    np.median(train_labels))),
            "checkpoint": checkpoint.name,
            "checkpointSha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        }
        report["folds"].append(fold)
        save()
        print(json.dumps({"fold": held_out + 1, "metrics": fold["model"]}), flush=True)
    if arguments.fit_all and time.monotonic() < deadline - 60:
        features = np.concatenate([session[0] for session in sessions])
        labels = np.concatenate([session[1] for session in sessions])
        model, completed_epochs, epoch_seconds = train(features, labels, "All rides", 20260918)
        checkpoint = arguments.output / "all-rides-candidate.weights.h5"
        model.save_weights(checkpoint)
        report["allRideCandidate"] = {
            "checkpoint": checkpoint.name, "completedEpochs": completed_epochs,
            "epochSeconds": epoch_seconds, "trainWindows": len(labels),
            "checkpointSha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "deploymentApproved": False, "hasIndependentEvaluation": False,
        }
    report["status"] = "completed" if (len(report["folds"]) == len(sessions) and all(
        fold["completedEpochs"] == arguments.epochs and not fold["trainingStoppedForBudget"]
        for fold in report["folds"]
    )) else "budget_stopped"
    if (arguments.fit_all
            and report.get("allRideCandidate", {}).get("completedEpochs") != arguments.epochs):
        report["status"] = "budget_stopped"
    save()
    print(f"{report['status']}: diagnostic only; installed Android model unchanged", flush=True)


if __name__ == "__main__":
    main()
