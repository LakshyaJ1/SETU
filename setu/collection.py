"""Validate Android training bundles and produce leakage-grouped IMU speed windows."""

from __future__ import annotations

import argparse
import hashlib
import json
from array import array
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import numpy as np

MAX_MEMBER_BYTES = 2 * 1024**3
SPLITS = {"train", "validation", "calibration", "test"}
TRAINING_VEHICLES = {"Car", "Two-wheeler"}


def read_record(stream):
    line = stream.readline(65538)
    if not line:
        return None
    if len(line) > 65536:
        raise ValueError("Oversized recording line")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Recording must contain JSON objects")
    return value


def verify_bundle(archive):
    names = archive.namelist()
    if sorted(names) != ["aligned.jsonl", "manifest.json", "raw.setulog"]:
        raise ValueError("Unexpected or duplicate bundle members")
    if any(member.file_size > MAX_MEMBER_BYTES for member in archive.infolist()):
        raise ValueError("Training bundle member exceeds 2 GB")
    if archive.getinfo("manifest.json").file_size > 65536:
        raise ValueError("Oversized manifest")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("schema") != "setu.training-bundle.v1":
        raise ValueError("Unsupported training bundle")
    for name in ("raw.setulog", "aligned.jsonl"):
        expected = manifest["files"][name]
        digest = hashlib.sha256()
        size = 0
        with archive.open(name) as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
            raise ValueError(f"Integrity mismatch: {name}")
    return manifest


def reference_valid(record):
    limits = {
        "latitude": (-90, 90),
        "longitude": (-180, 180),
        "accuracyMeters": (0, 10),
        "speedMps": (0, 45),
        "speedAccuracyMps": (0, 1.5),
    }
    return (
        record.get("provider") == "gps"
        and record.get("mock") is False
        and all(
            isinstance(record.get(key), (int, float))
            and not isinstance(record[key], bool)
            and np.isfinite(record[key])
            and low <= record[key] <= high
            for key, (low, high) in limits.items()
        )
    )


def convert_bundle(path, vehicle="Car", *, diagnostic=False):
    if vehicle not in TRAINING_VEHICLES:
        raise ValueError("Unsupported training vehicle")
    with ZipFile(path) as archive:
        manifest = verify_bundle(archive)
        issues = manifest.get("issues")
        if not isinstance(issues, list) or any(not isinstance(issue, str) for issue in issues):
            raise ValueError("Invalid session issues")
        blocking = [
            issue for issue in issues
            if not (vehicle == "Two-wheeler" and issue == "vehicle_outside_current_speed_model")
            and not (diagnostic and issue == "mount_unconfirmed")
        ]
        if (
            not manifest.get("complete")
            or blocking
            or manifest.get("droppedRecords") != 0
        ):
            raise ValueError(
                f"Session is ineligible: incomplete, changed configuration, drops or {blocking}"
            )
        with archive.open("raw.setulog") as stream:
            header = read_record(stream)
            if header != manifest["recording"]:
                raise ValueError("Raw header differs from manifest")
            collection = header.get("collection", {})
            if (
                collection.get("schema") != "setu.collection.v1"
                or collection.get("frame") != "phone_body"
                or collection.get("accelerationUnits") != "m/s^2 including gravity"
                or collection.get("gyroscopeUnits") != "rad/s"
                or header.get("clock") != "elapsedRealtimeNanos"
                or header.get("synthetic")
            ):
                raise ValueError("Unsupported collection provenance, clock, units or frame")
            if collection.get("vehicle") != vehicle or (
                collection.get("mount") != "fixed" and not (
                    diagnostic and collection.get("mount") == "unconfirmed"
                )
            ):
                raise ValueError(
                    f"Training requires a confirmed fixed-mount {vehicle}; "
                    "do not relabel recordings"
                )
            for key in ("sessionId", "installationId"):
                if not isinstance(collection.get(key), str) or not collection[key]:
                    raise ValueError(f"Missing collection {key}")
            start = header["startedAtNs"]
            samples = {name: array("d") for name in ("accelerometer", "gyroscope")}
            previous = dict.fromkeys(samples, -1)
            references = {}
            end = None
            while (record := read_record(stream)) is not None:
                if end is not None:
                    raise ValueError("Data after recording end")
                timestamp = record["tNs"]
                if not isinstance(timestamp, int) or timestamp < 0 or timestamp - start > 21600e9:
                    raise ValueError("Invalid recording timestamp")
                kind = record["type"]
                if timestamp < start:
                    continue
                if kind in samples:
                    values = record["values"][:3]
                    if (
                        timestamp <= previous[kind]
                        or len(values) != 3
                        or not np.all(np.isfinite(values))
                    ):
                        raise ValueError(f"Invalid or non-monotonic {kind}")
                    previous[kind] = timestamp
                    samples[kind].extend([(timestamp - start) / 1e9, *values])
                elif kind == "gnss_reference" and record.get("provider") == "gps":
                    existing = references.get(timestamp)
                    if existing is not None and any(
                        existing.get(key) != record.get(key)
                        for key in ("latitude", "longitude", "speedMps")
                    ):
                        raise ValueError("Conflicting GPS observations at the same timestamp")
                    references[timestamp] = record
                elif kind == "collection_change":
                    raise ValueError("Collection configuration changed mid-session")
                elif kind == "end":
                    if record.get("droppedRecords") != 0:
                        raise ValueError("Recording dropped data")
                    end = timestamp
            if end is None or end < max(previous.values()):
                raise ValueError("Missing or invalid end marker")

    streams = {kind: np.asarray(values).reshape(-1, 4) for kind, values in samples.items()}
    ordered = [references[timestamp] for timestamp in sorted(references)]
    gps_times = np.array([(record["tNs"] - start) / 1e9 for record in ordered])
    windows, labels, positions, times, uncertainties = [], [], [], [], []
    rejected = Counter()
    for target in np.arange(4.0, (end - start) / 1e9 + 1e-6, 1.0):
        upper = int(np.searchsorted(gps_times, target, side="left"))
        lower = upper if upper < len(gps_times) and gps_times[upper] == target else upper - 1
        if lower < 0 or upper >= len(ordered) or gps_times[upper] - gps_times[lower] > 1.5:
            rejected["gps_missing_or_gap"] += 1
            continue
        if not all(reference_valid(ordered[index]) for index in {lower, upper}):
            rejected["gps_quality"] += 1
            continue
        grid = target - np.arange(399, -1, -1) / 100
        channels = []
        for kind, values in streams.items():
            lower_sample = np.searchsorted(values[:, 0], grid[0], side="right") - 1
            upper_sample = np.searchsorted(values[:, 0], grid[-1], side="left")
            if lower_sample < 0 or upper_sample >= len(values):
                break
            block = values[lower_sample : upper_sample + 1]
            if (
                len(block) < 200
                or np.max(np.diff(block[:, 0])) > 0.0500001
                or np.max(np.abs(block[:, 1:])) >= (78 if kind == "accelerometer" else 16)
            ):
                break
            channels.extend(np.interp(grid, block[:, 0], block[:, axis]) for axis in (1, 2, 3))
        if len(channels) != 6:
            rejected["imu_gap_rate_or_saturation"] += 1
            continue
        fraction = (
            0
            if lower == upper
            else (target - gps_times[lower]) / (gps_times[upper] - gps_times[lower])
        )
        interpolated = {
            key: ordered[lower][key] * (1 - fraction) + ordered[upper][key] * fraction
            for key in ("speedMps", "latitude", "longitude")
        }
        windows.append(np.stack(channels, axis=1))
        labels.append(interpolated["speedMps"])
        positions.append([interpolated["latitude"], interpolated["longitude"]])
        uncertainties.append(
            max(ordered[lower]["speedAccuracyMps"], ordered[upper]["speedAccuracyMps"])
        )
        times.append(start + round(target * 1e9))
    metadata = {
        "sessionId": collection["sessionId"],
        "installationId": collection["installationId"],
        "utcDay": datetime.fromtimestamp(header["startedAtMs"] / 1000, timezone.utc)
        .date()
        .isoformat(),
        "sourceSha256": manifest["files"]["raw.setulog"]["sha256"],
        "vehicle": collection["vehicle"],
        "mount": collection["mount"],
        "diagnosticOnly": diagnostic,
        "sessionIssues": issues,
        "acceptedWindows": len(windows),
        "rejectedWindows": dict(rejected),
        "labelSource": "quality-filtered Android GNSS speed; not ground truth",
    }
    tensors = {
        "imu": np.asarray(windows, dtype=np.float32).reshape(-1, 400, 6),
        "speed_mps": np.asarray(labels, dtype=np.float32),
        "gps_lat_lon": np.asarray(positions, dtype=np.float64).reshape(-1, 2),
        "speed_accuracy_mps": np.asarray(uncertainties, dtype=np.float32),
        "timestamp_ns": np.asarray(times, dtype=np.int64),
    }
    return tensors, metadata


def build_dataset(plan_path, output, vehicle="Car"):
    if vehicle not in TRAINING_VEHICLES:
        raise ValueError("Unsupported training vehicle")
    plan_path, output = Path(plan_path), Path(output)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, list) or not plan:
        raise ValueError("Plan must be a nonempty list of bundle/group/split assignments")
    output.mkdir(parents=True, exist_ok=False)
    groups, device_days, identities = {}, {}, set()
    results = []
    for index, entry in enumerate(plan):
        split, group = entry["split"], entry["group"]
        if split not in SPLITS or not isinstance(group, str) or not group.strip():
            raise ValueError("Each session needs an explicit group and valid split")
        tensors, metadata = convert_bundle(plan_path.parent / entry["bundle"], vehicle=vehicle)
        identity = metadata["sessionId"]
        source_hash = metadata["sourceSha256"]
        if identity in identities or source_hash in identities:
            raise ValueError("Duplicate recording in split plan")
        identities.update((identity, source_hash))
        device_day = (metadata["installationId"], metadata["utcDay"])
        if (
            groups.setdefault(group, split) != split
            or device_days.setdefault(device_day, split) != split
        ):
            raise ValueError("Leakage: a group or phone/day crosses splits")
        if not metadata["acceptedWindows"]:
            raise ValueError(
                f"No eligible windows in {entry['bundle']}: {metadata['rejectedWindows']}"
            )
        filename = f"{index:04d}-{split}.npz"
        np.savez_compressed(output / filename, **tensors)
        digest = hashlib.sha256((output / filename).read_bytes()).hexdigest()
        results.append(
            {**metadata, "group": group, "split": split, "file": filename, "sha256": digest}
        )
    report = {
        "schema": "setu.phone-dataset.v1",
        "windowSamples": 400,
        "canonicalRateHz": 100,
        "channels": ["accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"],
        "deploymentApproved": False,
        "vehicle": vehicle,
        "sessions": results,
    }
    (output / "dataset.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON list of bundle/group/split assignments")
    parser.add_argument(
        "output", type=Path, help="New output directory; never overwrites a dataset"
    )
    parser.add_argument("--vehicle", choices=sorted(TRAINING_VEHICLES), default="Car")
    arguments = parser.parse_args()
    report = build_dataset(arguments.plan, arguments.output, vehicle=arguments.vehicle)
    print(
        json.dumps(
            {
                "sessions": len(report["sessions"]),
                "windows": sum(session["acceptedWindows"] for session in report["sessions"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
