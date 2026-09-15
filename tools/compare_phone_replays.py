"""Compare matched phone replays without dropping newly missing position estimates."""

import argparse
import json
import math
import re
from pathlib import Path


def within_target(row):
    error = row.get("errorMeters")
    return row["available"] and error is not None and math.isfinite(error) and 0 <= error <= 10


def compare_rows(previous, current):
    result = {"outputs": 0, "availableBefore": 0, "availableAfter": 0,
              "within10Before": 0, "within10After": 0, "previouslyAvailableLost": 0,
              "previousSuccessesLost": 0, "comparableInBoth": 0,
              "maxCommonErrorIncreaseMeters": None}
    for before, after in zip(previous, current, strict=True):
        for key in ("cycle", "outageElapsedSeconds", "recordingElapsedSeconds"):
            if before[key] != after[key]:
                raise ValueError("Cannot compare different scoring timelines")
        for row in (before, after):
            if type(row.get("available")) is not bool:
                raise ValueError("Invalid availability flag")
            if row.get("errorMeters") is not None and (
                not row["available"] or not math.isfinite(row["errorMeters"])
                or row["errorMeters"] < 0
            ):
                raise ValueError("Invalid comparison error")
        result["outputs"] += 1
        result["availableBefore"] += before["available"]
        result["availableAfter"] += after["available"]
        result["within10Before"] += within_target(before)
        result["within10After"] += within_target(after)
        result["previouslyAvailableLost"] += before["available"] and not after["available"]
        result["previousSuccessesLost"] += within_target(before) and not within_target(after)
        if before.get("errorMeters") is not None and after.get("errorMeters") is not None:
            result["comparableInBoth"] += 1
            increase = after["errorMeters"] - before["errorMeters"]
            previous_maximum = result["maxCommonErrorIncreaseMeters"]
            result["maxCommonErrorIncreaseMeters"] = increase if previous_maximum is None else max(
                previous_maximum, increase
            )
    return result


def compare_directories(baseline, candidate):
    def summaries(directory):
        rows = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
        indexed = {(row["recordingId"], row["outageSeconds"]): row for row in rows}
        if not rows or len(indexed) != len(rows):
            raise ValueError("Empty or duplicate experiment summaries")
        return indexed

    previous = summaries(baseline)
    current = summaries(candidate)
    if previous.keys() != current.keys():
        raise ValueError("Both experiments must contain the same recordings and durations")
    cases = []
    for (identifier, duration), before in previous.items():
        if not re.fullmatch(r"[a-f0-9-]{36}", identifier) or duration not in (10, 30, 60, 120, 180):
            raise ValueError("Invalid recording or outage identifier")
        after = current[(identifier, duration)]
        for key in ("sourceSha256", "warmupSeconds", "outageSeconds", "scoreHz", "cycles",
                    "outputs", "referenceAvailable"):
            if before[key] != after[key]:
                raise ValueError(f"Experiment mismatch: {key}")
        name = f"{identifier}-{duration}.jsonl"
        with (baseline / name).open() as old_stream, (candidate / name).open() as new_stream:
            result = compare_rows(map(json.loads, old_stream), map(json.loads, new_stream))
        for key, before_key, after_key in (
            ("outputs", "outputs", "outputs"),
            ("available", "availableBefore", "availableAfter"),
            ("within10Meters", "within10Before", "within10After"),
        ):
            if before[key] != result[before_key] or after[key] != result[after_key]:
                raise ValueError(f"Trace does not match summary: {key}")
        cases.append({"recordingId": identifier, "outageSeconds": duration,
                      "sourceSha256": before["sourceSha256"], **result})
    return {
        "schema": "setu.phone-replay-comparison.v1", "cases": cases,
        "allPreviousSuccessesRetained": all(
            case["previousSuccessesLost"] == 0 for case in cases
        ),
        "allPreviousAvailabilityRetained": all(
            case["previouslyAvailableLost"] == 0 for case in cases
        ),
        "deploymentApproved": False,
        "reference": "Development replay against withheld phone GPS, not field validation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    report = compare_directories(arguments.baseline, arguments.candidate)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}))


if __name__ == "__main__":
    main()
