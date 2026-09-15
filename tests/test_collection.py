"""Phone dataset provenance, synchronization and leakage regression tests."""

import hashlib
import json
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest

from notebooks.finetune_phone import load_dataset
from setu.collection import build_dataset, convert_bundle


def bundle(
    path,
    *,
    mock=False,
    gap=False,
    speed_accuracy=0.4,
    session="session-1",
    day=0,
    vehicle="Car",
    mount="fixed",
    issues=None,
    complete=True,
    tamper=False,
):
    start = 10_000_000_000
    header = {
        "schema": "setu.log.v1",
        "clock": "elapsedRealtimeNanos",
        "startedAtNs": start,
        "startedAtMs": 1_750_000_000_000 + day * 86400000,
        "synthetic": False,
        "collection": {
            "schema": "setu.collection.v1",
            "sessionId": session,
            "installationId": "phone-1",
            "vehicle": vehicle,
            "mount": mount,
            "frame": "phone_body",
            "accelerationUnits": "m/s^2 including gravity",
            "gyroscopeUnits": "rad/s",
        },
    }
    records = [header]
    for index in range(601):
        timestamp = start + index * 10_000_000
        for kind, values in (("accelerometer", [0, 0, 9.8]), ("gyroscope", [0, 0, 0.1])):
            if not gap or not 200 < index < 220:
                records.append({"type": kind, "tNs": timestamp, "values": values})
        if index % 100 == 0:
            records.append(
                {
                    "type": "gnss_reference",
                    "tNs": timestamp,
                    "provider": "gps",
                    "mock": mock,
                    "latitude": 28.0,
                    "longitude": 77.0,
                    "speedMps": 10.0,
                    "accuracyMeters": 3.0,
                    "speedAccuracyMps": speed_accuracy,
                }
            )
            records.append({"type": "native_pose", "tNs": timestamp, "speedMps": 99.0})
    if complete:
        records.append({"type": "end", "tNs": start + 6_000_000_000, "droppedRecords": 0})
    raw = "\n".join(json.dumps(record) for record in records).encode() + b"\n"
    files = {"raw.setulog": raw, "aligned.jsonl": b""}
    manifest = {
        "schema": "setu.training-bundle.v1",
        "recording": header,
        "complete": complete,
        "droppedRecords": 0,
        "issues": issues or [],
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data + (b" " if tamper and name == "raw.setulog" else b""))
        archive.writestr("manifest.json", json.dumps(manifest))
    return path


def test_keeps_gps_out_of_imu_and_does_not_train_on_fused_prediction(tmp_path):
    tensors, metadata = convert_bundle(bundle(tmp_path / "drive.zip"))
    assert tensors["imu"].shape == (3, 400, 6)
    np.testing.assert_allclose(tensors["speed_mps"], 10.0)
    np.testing.assert_allclose(tensors["imu"][:, :, 2], 9.8)
    np.testing.assert_allclose(tensors["imu"][:, :, 5], 0.1)
    assert metadata["acceptedWindows"] == 3


def test_diagnostic_conversion_preserves_unconfirmed_mount_and_never_weakens_default(tmp_path):
    path = bundle(tmp_path / "diagnostic.zip", vehicle="Two-wheeler", mount="unconfirmed",
                  issues=["mount_unconfirmed", "vehicle_outside_current_speed_model"])
    with pytest.raises(ValueError, match="ineligible"):
        convert_bundle(path, vehicle="Two-wheeler")
    tensors, metadata = convert_bundle(path, vehicle="Two-wheeler", diagnostic=True)
    assert metadata["diagnosticOnly"] and metadata["mount"] == "unconfirmed"
    assert metadata["acceptedWindows"] == 3
    assert tensors["imu"].shape == (3, 400, 6)
    invalid = bundle(tmp_path / "changed.zip", issues=["configuration_changed"])
    with pytest.raises(ValueError, match="ineligible"):
        convert_bundle(invalid, diagnostic=True)


def test_diagnostic_metadata_cannot_enter_production_finetuning(tmp_path):
    bundle(tmp_path / "drive.zip")
    (tmp_path / "plan.json").write_text(json.dumps([
        {"bundle": "drive.zip", "split": "train", "group": "research"}
    ]))
    report = build_dataset(tmp_path / "plan.json", tmp_path / "dataset")
    report["sessions"][0]["diagnosticOnly"] = True
    (tmp_path / "dataset/dataset.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Diagnostic cohort"):
        load_dataset(tmp_path / "dataset", minimum_windows=3)


@pytest.mark.parametrize("options", [{"mock": True}, {"speed_accuracy": None}, {"gap": True}])
def test_bad_references_and_sensor_gaps_are_not_training_examples(tmp_path, options):
    tensors, metadata = convert_bundle(bundle(tmp_path / "drive.zip", **options))
    assert len(tensors["imu"]) == 0
    assert sum(metadata["rejectedWindows"].values()) == 3


@pytest.mark.parametrize(
    "options", [{"tamper": True}, {"complete": False}, {"vehicle": "Heavy vehicle"}]
)
def test_rejects_integrity_incomplete_and_unsupported_vehicle(tmp_path, options):
    with pytest.raises(ValueError):
        convert_bundle(bundle(tmp_path / "drive.zip", **options))


@pytest.mark.parametrize("different_day,same_group", [(False, False), (True, True)])
def test_split_plan_rejects_phone_day_and_collection_group_leakage(
    tmp_path, different_day, same_group
):
    bundle(tmp_path / "first.zip")
    bundle(tmp_path / "second.zip", session="session-2", day=int(different_day))
    plan = [
        {"bundle": "first.zip", "split": "train", "group": "route-A"},
        {"bundle": "second.zip", "split": "test", "group": "route-A" if same_group else "route-B"},
    ]
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="Leakage"):
        build_dataset(tmp_path / "plan.json", tmp_path / "dataset")
    assert not (tmp_path / "dataset/dataset.json").exists()


def test_dataset_has_hashes_and_never_overwrites_previous_data(tmp_path):
    bundle(tmp_path / "drive.zip")
    (tmp_path / "plan.json").write_text(
        json.dumps([{"bundle": "drive.zip", "split": "train", "group": "driver-A-route-A"}])
    )
    report = build_dataset(tmp_path / "plan.json", tmp_path / "dataset")
    assert report["deploymentApproved"] is False
    assert len(report["sessions"][0]["sha256"]) == 64
    with pytest.raises(FileExistsError):
        build_dataset(tmp_path / "plan.json", tmp_path / "dataset")


def test_finetuning_preflight_requires_four_separate_splits_and_checks_shards(tmp_path):
    plan = []
    for index, split in enumerate(("train", "validation", "calibration", "test")):
        filename = f"{split}.zip"
        bundle(tmp_path / filename, session=f"session-{index}", day=index)
        plan.append({"bundle": filename, "split": split, "group": f"group-{index}"})
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    build_dataset(tmp_path / "plan.json", tmp_path / "dataset")
    loaded = load_dataset(tmp_path / "dataset", minimum_windows=3)
    assert all(features.shape == (3, 400, 6) for features, _ in loaded.values())
    with pytest.raises(ValueError, match="100 quality windows"):
        load_dataset(tmp_path / "dataset")
    shard = tmp_path / "dataset/0000-train.npz"
    shard.write_bytes(shard.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        load_dataset(tmp_path / "dataset", minimum_windows=3)


def test_two_wheeler_requires_explicit_target_and_preserves_provenance(tmp_path):
    path = bundle(tmp_path / "scooter.zip", vehicle="Two-wheeler",
                  issues=["vehicle_outside_current_speed_model"])
    with pytest.raises(ValueError):
        convert_bundle(path)
    tensors, metadata = convert_bundle(path, vehicle="Two-wheeler")
    assert len(tensors["imu"]) == 3
    assert metadata["vehicle"] == "Two-wheeler"
    assert metadata["mount"] == "fixed"
    assert metadata["sessionIssues"] == ["vehicle_outside_current_speed_model"]


@pytest.mark.parametrize("mount,issues", [
    ("unconfirmed", ["vehicle_outside_current_speed_model"]),
    ("fixed", ["vehicle_outside_current_speed_model", "configuration_changed"]),
    ("fixed", ["vehicle_outside_current_speed_model", "mount_unconfirmed"]),
])
def test_scooter_opt_in_does_not_bypass_mount_or_session_quality(tmp_path, mount, issues):
    path = bundle(tmp_path / "scooter.zip", vehicle="Two-wheeler", mount=mount, issues=issues)
    with pytest.raises(ValueError):
        convert_bundle(path, vehicle="Two-wheeler")


def test_two_wheeler_dataset_cannot_be_passed_off_as_car(tmp_path):
    bundle(tmp_path / "scooter.zip", vehicle="Two-wheeler")
    (tmp_path / "plan.json").write_text(json.dumps([
        {"bundle": "scooter.zip", "split": "train", "group": "scooter-route-A"}
    ]))
    report = build_dataset(tmp_path / "plan.json", tmp_path / "dataset", vehicle="Two-wheeler")
    assert report["vehicle"] == "Two-wheeler"
    assert report["sessions"][0]["vehicle"] == "Two-wheeler"
    report["vehicle"] = "Car"
    (tmp_path / "dataset/dataset.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="mixes vehicles"):
        load_dataset(tmp_path / "dataset", minimum_windows=3)
