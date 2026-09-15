"""Summarize sensor and estimator failures without printing personal coordinates."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def summarize(path):
    records = defaultdict(list)
    with Path(path).open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        for line in stream:
            record = json.loads(line)
            records[record["type"]].append(record)
    started = header["startedAtNs"]
    report = {
        "file": Path(path).name,
        "collection": {key: header.get("collection", {}).get(key) for key in ("vehicle", "mount")},
        "counts": {kind: len(values) for kind, values in records.items()},
    }
    for kind in ("accelerometer", "gyroscope", "magnetometer"):
        samples = records[kind]
        if not samples:
            continue
        vectors = np.array([record["values"][:3] for record in samples])
        times = np.array([record["tNs"] for record in samples], dtype=np.int64)
        magnitudes = np.linalg.norm(vectors, axis=1)
        differences = np.diff(times) / 1e9
        largest = np.argsort(magnitudes)[-5:]
        report[kind] = {
            "magnitude_p50_p95_p99_max": np.quantile(magnitudes, [0.5, 0.95, 0.99, 1])
            .round(5)
            .tolist(),
            "rate_hz": round(float(1 / np.median(differences)), 2)
            if differences.size and np.median(differences) > 0
            else None,
            "gap_max_ms": round(float(differences.max() * 1000), 3) if differences.size else None,
            "nonmonotonic": int(np.sum(differences <= 0)),
            "accuracy": dict(Counter(record.get("accuracy") for record in samples)),
            "peaks": [
                {
                    "seconds": round((int(times[index]) - started) / 1e9, 3),
                    "values": vectors[index].round(4).tolist(),
                }
                for index in largest
            ],
        }
    for kind in ("gnss_reference", "pose", "native_pose", "track_pose", "model_measurement"):
        samples = records[kind]
        speeds = [record["speedMps"] for record in samples if record.get("speedMps") is not None]
        report[kind] = {
            "speed_p50_p95_max": np.quantile(speeds, [0.5, 0.95, 1]).round(4).tolist()
            if speeds
            else [],
            "sources": dict(
                Counter(record.get("source", record.get("status")) for record in samples)
            ),
        }
    rotations = records["game_rotation_vector"]
    gyro = records["gyroscope"]
    if len(rotations) > 1 and gyro:
        times = np.array([record["tNs"] for record in gyro], dtype=np.int64)
        vectors = np.array([record["values"][:3] for record in gyro])
        errors = []
        for before, after in zip(rotations, rotations[1:], strict=False):
            interval = (after["tNs"] - before["tNs"]) / 1e9
            lower, upper = np.searchsorted(times, [before["tNs"], after["tNs"]])
            if upper <= lower or len(before["values"]) < 4 or len(after["values"]) < 4:
                continue
            observed = Rotation.from_quat(before["values"][:4]).inv() * Rotation.from_quat(
                after["values"][:4]
            )
            predicted = Rotation.from_rotvec(vectors[lower:upper].mean(axis=0) * interval)
            errors.append(float(np.degrees((observed.inv() * predicted).magnitude())))
        if errors:
            report["gyro_rotation_agreement_degrees_p50_p95_p99_max"] = (
                np.quantile(errors, [0.5, 0.95, 0.99, 1]).round(3).tolist()
            )
    report["native_states"] = dict(
        Counter(record.get("status") for record in records["native_state"])
    )
    report["location_states"] = [
        {"seconds": round((record["tNs"] - started) / 1e9, 2), "enabled": record["enabled"]}
        for record in records["location_state"]
    ]
    report["native_seconds"] = [
        {
            "seconds": round((record["tNs"] - started) / 1e9, 2),
            "speed": record.get("speedMps"),
            "gps_age": record.get("gpsAgeSeconds"),
            "radius": record.get("radius95Meters"),
            "heading": record.get("headingSource"),
        }
        for record in records["native_pose"][::10]
    ]
    report["gps_seconds"] = [
        {
            "seconds": round((record["tNs"] - started) / 1e9, 2),
            "speed": record.get("speedMps"),
            "accuracy": record.get("accuracyMeters"),
            "speed_accuracy": record.get("speedAccuracyMps"),
            "provider": record.get("provider"),
        }
        for record in records["gnss_reference"]
        if record.get("provider") == "gps"
    ]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.write_text(
        json.dumps([summarize(path) for path in arguments.recordings], indent=2), encoding="utf-8"
    )
