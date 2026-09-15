import json

from tools.analyze_recording import summarize


def test_sparse_recording_keeps_raw_research_separate_and_omits_coordinates(tmp_path):
    source = tmp_path / "sparse.setulog"
    records = [
        {"startedAtNs": 100, "collection": {"vehicle": "Walking"}},
        {"type": "accelerometer", "tNs": 101, "values": [0, 0, 9.8], "accuracy": 3},
        {"type": "pose", "tNs": 101, "speedMps": 0, "latitude": 28.7, "longitude": 77.2},
        {"type": "model_measurement", "tNs": 101, "speedMps": 30, "status": "Research"},
    ]
    source.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    report = summarize(source)
    assert report["accelerometer"]["rate_hz"] is None
    assert report["pose"]["speed_p50_p95_max"] == [0, 0, 0]
    assert report["model_measurement"]["speed_p50_p95_max"] == [30, 30, 30]
    assert "latitude" not in json.dumps(report)
    assert "longitude" not in json.dumps(report)
