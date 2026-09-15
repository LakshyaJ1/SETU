import json
from pathlib import Path

import pytest

from tools.run_road_stress import PROFILES


def test_dossier_renders_and_requires_all_conditions(tmp_path):
    pytest.importorskip("reportlab")
    from tools.build_metrics_pdf import build

    report = {
        "synthetic": True, "releaseApproved": False, "trials": 675,
        "conditions": 135, "repeats": 5,
        "cases": [
            {"algorithm": algorithm, "durationSeconds": duration, "profile": profile,
             "jointSuccess": .5, "availability": .8, "unavailableEnds": 5, "runs": 5}
            for algorithm in ("cv", "imu", "car") for duration in (10, 30, 60, 120, 180)
            for profile in PROFILES
        ],
    }
    comparison = tmp_path / "comparison.json"
    comparison.write_text(json.dumps(report))
    model = Path("android/app/src/main/assets/models/setu-speed-v1/manifest.json")
    output = tmp_path / "metrics.pdf"
    build(comparison, model, output)
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 10_000
    rides = tmp_path / "rides.json"
    rides.write_text(json.dumps([
        {"ride": name, "outageSeconds": duration, "outputs": 1801,
         "available": 20, "referenceAvailable": 1500, "within10Meters": 10}
        for name in ("9.007 km", "2.387 km", "3.423 km")
        for duration in (10, 30, 60, 120, 180)
    ]))
    build(comparison, model, output, rides)
    assert output.read_bytes().startswith(b"%PDF-")
    pooled = tmp_path / "pooled.json"
    pooled.write_text(json.dumps({
        "deploymentApproved": False,
        "cases": [
            {"recordingId": name, "sourceSha256": name, "outageSeconds": duration,
             "outputs": 1801, "availableBefore": 20, "availableAfter": 40,
             "within10After": 30, "previousSuccessesLost": 0, "previouslyAvailableLost": 0}
            for name in ("long-ride", "storage-ride", "stable-ride")
            for duration in (10, 30, 60, 120, 180)
        ],
    }))
    build(comparison, model, output, rides, pooled)
    assert output.read_bytes().startswith(b"%PDF-")
    training = tmp_path / "cpu.json"
    training.write_text(json.dumps({
        "deploymentApproved": False, "status": "completed", "elapsedSeconds": 408,
        "totalWindows": 2125, "folds": [
            {"ride": name, "model": {"maeMps": 2., "absoluteErrorP90Mps": 4.,
                                      "stationaryPredictedSpeedP90Mps": 1.},
             "trainMedianBaseline": {"maeMps": 3.}}
            for name in ("9.007 km", "2.387 km", "3.423 km")
        ],
    }))
    build(comparison, model, output, rides, pooled, training)
    assert output.read_bytes().startswith(b"%PDF-")
    report["cases"].pop()
    comparison.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="full paired"):
        build(comparison, model, output)


def test_dossier_never_silently_relabels_research_as_release(tmp_path):
    pytest.importorskip("reportlab")
    from tools.build_metrics_pdf import build

    comparison = tmp_path / "comparison.json"
    comparison.write_text(json.dumps({"synthetic": True, "releaseApproved": True}))
    model = Path("android/app/src/main/assets/models/setu-speed-v1/manifest.json")
    with pytest.raises(ValueError, match="research evidence"):
        build(comparison, model, tmp_path / "metrics.pdf")
