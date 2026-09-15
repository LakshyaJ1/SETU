import json

import pytest

from tools.run_road_stress import battery_ready, digest, validate_case
from tools.summarize_road_stress import compare_versions, interval95, summarize


def test_benchmark_requires_charging_safe_temperature_and_battery():
    assert battery_ready("USB powered: true\nlevel: 8\ntemperature: 370")[0]
    assert not battery_ready("USB powered: false\nlevel: 80\ntemperature: 370")[0]
    assert not battery_ready("USB powered: true\nlevel: 4\ntemperature: 370")[0]
    assert not battery_ready("USB powered: true\nlevel: 50\ntemperature: 430")[0]
    assert not battery_ready("")[0]


def fixture():
    identity = {"algorithm": "imu", "durationSeconds": 10, "profile": "stationary"}
    return [
        {"type": "protocol", "schema": "setu.road-stress.v1", "synthetic": True,
         "warmupSeconds": 120, "scoreHz": 10, "targetMeters": 10,
         "missingCountsAsFailure": True, "absoluteAttitudeDuringBlackout": False},
        {"type": "run", **identity, "seed": 0xBEEF, "outputs": 101, "available": 20,
         "within10Meters": 10, "jointSuccess": 10 / 101},
        {"type": "summary", **identity, "outputs": 101, "runs": 1, "available": 20,
         "jointSuccess": 10 / 101, "releaseApproved": False},
    ]


def test_missing_predictions_are_not_dropped_from_accuracy(tmp_path):
    path = tmp_path / "case.jsonl"
    rows = fixture()
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert validate_case(path, "imu", 10, 0, 1)["outputs"] == 101
    rows[1]["jointSuccess"] = 10 / 20
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="excludes missing"):
        validate_case(path, "imu", 10, 0, 1)


def test_incomplete_or_wrong_experiments_cannot_be_resumed(tmp_path):
    path = tmp_path / "case.jsonl"
    rows = fixture()
    path.write_text("\n".join(json.dumps(row) for row in rows[:-1]))
    with pytest.raises(ValueError, match="Incomplete"):
        validate_case(path, "imu", 10, 0, 1)
    rows[1]["seed"] = 1
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="seeds"):
        validate_case(path, "imu", 10, 0, 1)
    rows[1]["seed"] = 0xBEEF
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="requested case"):
        validate_case(path, "car", 10, 0, 1)


@pytest.mark.parametrize("key,value", [
    ("available", 21), ("outputs", 20), ("jointSuccess", 1.0),
    ("jointSuccess", float("nan")), ("runs", 2), ("releaseApproved", True),
])
def test_inconsistent_aggregate_cannot_be_resumed(tmp_path, key, value):
    rows = fixture()
    rows[-1][key] = value
    path = tmp_path / "case.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="summary"):
        validate_case(path, "imu", 10, 0, 1)


@pytest.mark.parametrize("key,value", [
    ("warmupSeconds", 30), ("absoluteAttitudeDuringBlackout", True),
    ("missingCountsAsFailure", False),
])
def test_changed_protocol_cannot_be_resumed(tmp_path, key, value):
    rows = fixture()
    rows[0][key] = value
    path = tmp_path / "case.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="protocol"):
        validate_case(path, "imu", 10, 0, 1)


def test_uncertainty_resamples_runs_not_position_ticks():
    assert interval95([0.5]) is None
    assert interval95([0.5] * 5) == [0.5, 0.5]
    assert interval95([0, 0, 0, 1, 1]) == interval95([0, 0, 0, 1, 1])
    lower, upper = interval95([0, 0, 0, 1, 1])
    assert lower <= 0.4 <= upper


def test_incomplete_matrix_is_not_a_comparison(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "status": "paused", "releaseApproved": False,
    }))
    with pytest.raises(ValueError, match="completed"):
        summarize(tmp_path)


def experiment(directory, successes=10, physics="same-physics", device="same-device"):
    directory.mkdir()
    source = directory / "sources/core/test/dr_bench.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(physics)
    rows = fixture()
    rows[1]["within10Meters"] = successes
    rows[1]["jointSuccess"] = rows[-1]["jointSuccess"] = successes / 101
    case = directory / "imu-10-0.jsonl"
    case.write_text("\n".join(json.dumps(row) for row in rows))
    (directory / "manifest.json").write_text(json.dumps({
        "status": "completed", "releaseApproved": False,
        "configuration": {
            "algorithms": ["imu"], "durations": [10], "profiles": [0], "repeats": 1,
            "sources": {"core/test/dr_bench.cpp": digest(source)}, "binarySha256": "binary",
            "deviceIdSha256": device, "deviceModel": "fixture", "androidApi": "26",
        },
        "cases": [{"file": case.name, "sha256": digest(case), "summary": rows[-1]}],
    }))
    return directory


def test_version_comparison_keeps_missing_denominator_and_reports_regression(tmp_path):
    before = experiment(tmp_path / "before", successes=10)
    after = experiment(tmp_path / "after", successes=5)
    report = compare_versions(before, after)
    case = report["cases"][0]
    assert case["jointSuccessDifference"] == pytest.approx(-5 / 101)
    assert case["pairedBootstrapInterval95"] is None
    assert case["outputs"] == 101
    assert not report["releaseApproved"]


@pytest.mark.parametrize("setting", ["physics", "device"])
def test_version_comparison_rejects_changed_physics_or_device(tmp_path, setting):
    before = experiment(tmp_path / "before")
    after = experiment(tmp_path / "after", **{setting: "different"})
    with pytest.raises(ValueError, match="matching|identical"):
        compare_versions(before, after)


def test_source_tampering_invalidates_version_comparison(tmp_path):
    before = experiment(tmp_path / "before")
    after = experiment(tmp_path / "after")
    (after / "sources/core/test/dr_bench.cpp").write_text("tampered")
    with pytest.raises(ValueError, match="Source snapshot"):
        compare_versions(before, after)
