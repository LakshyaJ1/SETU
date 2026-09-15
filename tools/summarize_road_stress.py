"""Validate a completed synthetic matrix and write coordinate-free comparison evidence."""

import argparse
import itertools
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from tools.run_road_stress import PROFILES, digest, validate_case


def interval95(values, seed=731):
    if len(values) < 2:
        return None
    generator = random.Random(seed)
    means = sorted(
        sum(generator.choices(values, k=len(values))) / len(values) for _ in range(2000)
    )
    return [means[math.ceil(len(means) * fraction) - 1] for fraction in (0.025, 0.975)]


def summarize(directory):
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "completed" or manifest["releaseApproved"] is not False:
        raise ValueError("Only completed, explicitly synthetic experiments can be summarized")
    config = manifest["configuration"]
    expected = {
        f"{algorithm}-{duration}-{profile}.jsonl": (algorithm, duration, profile)
        for algorithm, duration, profile in itertools.product(
            config["algorithms"], config["durations"], config["profiles"]
        )
    }
    if (len(manifest["cases"]) != len(expected)
            or {case["file"] for case in manifest["cases"]} != set(expected)):
        raise ValueError("The matrix is incomplete or contains duplicate conditions")
    for name, checksum in config["sources"].items():
        path = directory / "sources" / name
        if digest(path) != checksum:
            raise ValueError(f"Source snapshot changed: {name}")
    cases = []
    matched = defaultdict(dict)
    for case in manifest["cases"]:
        name = case["file"]
        path = directory / name
        if digest(path) != case["sha256"]:
            raise ValueError(f"Benchmark output changed: {name}")
        algorithm, duration, profile = expected[name]
        summary = validate_case(path, algorithm, duration, profile, config["repeats"])
        if summary != case["summary"]:
            raise ValueError(f"Manifest summary disagrees with its source: {name}")
        runs = [row for row in map(json.loads, path.read_text().splitlines())
                if row.get("type") == "run"]
        scores = [row["within10Meters"] / row["outputs"] for row in runs]
        cases.append({
            **summary, "sourceSha256": case["sha256"],
            "availability": summary["available"] / summary["outputs"],
            "jointBootstrapInterval95": interval95(scores),
            "seedsWithClipping": sum(row.get("clippedSamples", 0) > 0 for row in runs),
            "seedsWithDropout": sum(row.get("droppedSamples", 0) > 0 for row in runs),
        })
        matched[(duration, profile)][algorithm] = {
            row["seed"]: row["within10Meters"] / row["outputs"] for row in runs
        }
    paired = []
    for (duration, profile), algorithms in matched.items():
        for first, second in itertools.combinations(sorted(algorithms), 2):
            if algorithms[first].keys() != algorithms[second].keys():
                raise ValueError("Algorithm comparisons must use identical seeds")
            differences = [algorithms[second][seed] - algorithms[first][seed]
                           for seed in sorted(algorithms[first])]
            paired.append({
                "durationSeconds": duration, "profile": PROFILES[profile],
                "comparison": f"{second} minus {first}", "runs": len(differences),
                "jointSuccessDifference": sum(differences) / len(differences),
                "pairedBootstrapInterval95": interval95(differences),
            })
    return {
        "schema": "setu.road-stress-comparison.v1", "synthetic": True,
        "releaseApproved": False, "manifestSha256": digest(manifest_path),
        "binarySha256": config["binarySha256"], "sources": config["sources"],
        "deviceModel": config["deviceModel"], "androidApi": config["androidApi"],
        "repeats": config["repeats"], "conditions": len(cases),
        "trials": len(cases) * config["repeats"], "cases": cases, "paired": paired,
        "uncertainty": "Exploratory percentile bootstrap: 2000 resamples of complete seeds, "
        "paired across algorithms. Few synthetic seeds do not establish field confidence.",
        "limitations": [
            "Synthetic stress physics, not measured Indian-road hazard prevalence.",
            "No Android heading initialization, learned model, map matching or GPS recovery test.",
            "Car constraints on leaning profiles are a negative control, not scooter support.",
            "Missing predictions count as failures; unavailable endpoints are null, not zero.",
            "Benchmark success is not approval against every project release gate.",
        ],
    }


def markdown(report):
    lines = [
        "# Synthetic road-stress comparison", "", "**Not field validation or release approval.**",
        "", f"{report['trials']} trials, {report['conditions']} conditions, "
        f"{report['repeats']} paired seeds on {report['deviceModel']}.",
        "120 s GPS warmup; 200 Hz IMU; 10 Hz scoring; no blackout GPS or absolute attitude.",
        "Missing outputs remain in the within-10-m denominator.", "",
        "CV holds the last GPS velocity. IMU is unconstrained native propagation. "
        "Car adds the current vehicle constraints; it is not applicable to scooter lean.", "",
        "| Algorithm | Profile | Outage s | Available % | Within 10 m % | "
        "Bootstrap 95% % | Missing ends | Benchmark |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        bounds = case["jointBootstrapInterval95"]
        uncertainty = "n/a" if bounds is None else f"{bounds[0]*100:.1f}–{bounds[1]*100:.1f}"
        verdict = "pass" if case["benchmarkTargetMet"] else "FAIL"
        lines.append(
            f"| {case['algorithm']} | {case['profile']} | {case['durationSeconds']} | "
            f"{case['availability']*100:.1f} | {case['jointSuccess']*100:.1f} | "
            f"{uncertainty} | {case['unavailableEnds']} | {verdict} |"
        )
    lines.extend(["", report["uncertainty"], "", "## Boundaries", ""])
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    lines.extend(["", f"Executable SHA-256: `{report['binarySha256']}`.",
                  f"Experiment manifest SHA-256: `{report['manifestSha256']}`.", ""])
    return "\n".join(lines)


def compare_versions(before_directory, after_directory):
    before = summarize(before_directory)
    after = summarize(after_directory)
    configs = [json.loads((directory / "manifest.json").read_text())["configuration"]
               for directory in (before_directory, after_directory)]
    for key in ("algorithms", "durations", "profiles", "repeats", "deviceIdSha256", "androidApi"):
        if configs[0].get(key) != configs[1].get(key):
            raise ValueError(f"Version comparison requires matching {key}")
    physics = "core/test/dr_bench.cpp"
    if (not before["sources"].get(physics)
            or before["sources"][physics] != after["sources"].get(physics)):
        raise ValueError("Version comparison requires identical benchmark physics")
    cases = []
    for algorithm, duration, profile in itertools.product(
        configs[0]["algorithms"], configs[0]["durations"], configs[0]["profiles"]
    ):
        name = f"{algorithm}-{duration}-{profile}.jsonl"
        rows = [[json.loads(line) for line in (directory / name).read_text().splitlines()]
                for directory in (before_directory, after_directory)]
        runs = [{row["seed"]: row for row in values if row["type"] == "run"} for values in rows]
        if runs[0].keys() != runs[1].keys():
            raise ValueError("Version comparison requires identical seeds")
        summaries = [next(row for row in values if row["type"] == "summary") for values in rows]
        differences = [runs[1][seed]["jointSuccess"] - runs[0][seed]["jointSuccess"]
                       for seed in sorted(runs[0])]
        cases.append({
            "algorithm": algorithm, "durationSeconds": duration, "profile": PROFILES[profile],
            "runs": len(differences), "outputs": summaries[0]["outputs"],
            "availableBefore": summaries[0]["available"],
            "availableAfter": summaries[1]["available"],
            "jointSuccessBefore": summaries[0]["jointSuccess"],
            "jointSuccessAfter": summaries[1]["jointSuccess"],
            "jointSuccessDifference": sum(differences) / len(differences),
            "pairedBootstrapInterval95": interval95(differences),
            "finalErrorP90BeforeMeters": summaries[0].get("finalErrorP90Meters"),
            "finalErrorP90AfterMeters": summaries[1].get("finalErrorP90Meters"),
            "unavailableEndsBefore": summaries[0].get("unavailableEnds"),
            "unavailableEndsAfter": summaries[1].get("unavailableEnds"),
            "benchmarkPassedBefore": summaries[0].get("benchmarkTargetMet", False),
            "benchmarkPassedAfter": summaries[1].get("benchmarkTargetMet", False),
        })
    return {
        "schema": "setu.road-stress-version-comparison.v1", "synthetic": True,
        "releaseApproved": False, "binaryBeforeSha256": before["binarySha256"],
        "binaryAfterSha256": after["binarySha256"],
        "manifestBeforeSha256": before["manifestSha256"],
        "manifestAfterSha256": after["manifestSha256"], "cases": cases,
        "uncertainty": after["uncertainty"],
        "limitations": "Development comparison on matched synthetic seeds, not unseen validation. "
        "Endpoint quantiles require the accompanying unavailable-end counts. "
        "Condition aggregates do not establish per-tick non-regression or field accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=Path)
    arguments = parser.parse_args()
    report = summarize(arguments.directory)
    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "comparison.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    (arguments.output / "comparison.md").write_text(markdown(report), encoding="utf-8")
    if arguments.baseline:
        regression = compare_versions(arguments.baseline, arguments.directory)
        (arguments.output / "regression.json").write_text(
            json.dumps(regression, indent=2, allow_nan=False), encoding="utf-8"
        )
    print(f"Validated {report['trials']} synthetic trials; no field-accuracy claim")


if __name__ == "__main__":
    main()
