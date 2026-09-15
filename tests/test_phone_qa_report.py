import json

import pytest

from tools.build_phone_qa_report import DURATIONS, build_report, main, read_suite, score


def test_missing_predictions_and_references_remain_in_accuracy_denominator():
    result = score([
        {"available": True, "referenceAvailable": True, "errorMeters": 2.0},
        {"available": True, "referenceAvailable": True, "errorMeters": 12.0},
        {"available": False, "referenceAvailable": True, "errorMeters": None},
        {"available": True, "referenceAvailable": False, "errorMeters": None},
    ])
    assert result["jointSuccessPercent"] == 25
    assert result["expected"] == 4
    assert result["comparable"] == 2
    with pytest.raises(ValueError):
        score([{"available": False, "referenceAvailable": True, "errorMeters": 0.0}])


def test_instrumentation_skips_and_errors_are_not_reported_as_passes(tmp_path):
    path = tmp_path / "instrumentation.log"
    path.write_text("""INSTRUMENTATION_STATUS: class=Example
INSTRUMENTATION_STATUS: test=needsFixture
INSTRUMENTATION_STATUS_CODE: -4
INSTRUMENTATION_STATUS: class=Example
INSTRUMENTATION_STATUS: test=broken
INSTRUMENTATION_STATUS: stack=Failure
INSTRUMENTATION_STATUS_CODE: -2
INSTRUMENTATION_CODE: -1
""")
    result = read_suite(path)
    assert result["counts"] == {"skipped": 1, "failed": 1}
    assert result["runnerCompleted"]
    path.write_text(path.read_text(), encoding="utf-16")
    assert read_suite(path)["counts"] == result["counts"]


def test_full_report_requires_complete_half_open_grids(tmp_path, monkeypatch):
    summaries = []
    for number in range(3):
        identifier = f"00000000-0000-0000-0000-{number:012d}"
        for duration in DURATIONS:
            rows = [{"cycle": 0, "outageElapsedSeconds": tick / 10,
                     "available": False, "referenceAvailable": True, "errorMeters": None}
                    for tick in range(duration * 10)]
            (tmp_path / f"{identifier}-{duration}.jsonl").write_text(
                "\n".join(map(json.dumps, rows)))
            summaries.append({"recordingId": identifier, "outageSeconds": duration,
                              "schema": "setu.phone-outage.v2", "apkSha256": "a" * 64,
                              "sourceSha256": "b" * 64, "warmupSeconds": 120, "scoreHz": 10,
                              "cycles": 1, "outputs": len(rows), "available": 0,
                              "referenceAvailable": len(rows), "comparable": 0,
                              "within10Meters": 0})
    (tmp_path / "summary.json").write_text(json.dumps(summaries))
    report = build_report(tmp_path)
    assert all(row["jointSuccessPercent"] == 0 for row in report["durations"])
    assert [row["expected"] for row in report["matched90SecondPhases"]] == [300] * 5 + [1200]
    checks = tmp_path / "checks.json"
    checks.write_text(json.dumps({"apkSha256": "a" * 64, "checks": [], "findings": []}))
    assert build_report(tmp_path, checks_path=checks)["supplementaryChecks"] is not None
    checks.write_text("{}")
    with pytest.raises(ValueError, match="different APK"):
        build_report(tmp_path, checks_path=checks)
    suite = tmp_path / "suite"
    suite.mkdir()
    logged = ("INSTRUMENTATION_STATUS: class=Example\n"
              "INSTRUMENTATION_STATUS: test=first\n"
              "INSTRUMENTATION_STATUS_CODE: 0\n")
    (suite / "001-first.log").write_text(logged + "INSTRUMENTATION_CODE: -1\n")
    (suite / "discovery.log").write_text(logged + logged.replace("first", "missing") +
                                        "INSTRUMENTATION_CODE: -1\n")
    monkeypatch.setattr("sys.argv", ["build_phone_qa_report", str(tmp_path),
                                    str(tmp_path / "output"), "--suite-directory", str(suite)])
    with pytest.raises(ValueError, match="complete discovered test inventory"):
        main()
    (suite / "001-first.log").unlink()
    with pytest.raises(ValueError, match="complete discovered test inventory"):
        main()
    trace = tmp_path / "00000000-0000-0000-0000-000000000000-10.jsonl"
    trace.write_text(trace.read_text() + "\n" + trace.read_text().splitlines()[0])
    with pytest.raises(ValueError, match="Incomplete scoring grid"):
        build_report(tmp_path)
