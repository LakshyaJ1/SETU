"""Run Android test methods in fresh instrumentation processes without clearing user data."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from tools.build_phone_qa_report import read_suite


def run(adb, serial, directory, classes=None):
    directory.mkdir(parents=True, exist_ok=True)
    prefix = [str(adb), "-s", serial, "shell", "am", "instrument", "-w", "-r",
              "-e", "physicalHardware", "true"]
    runner = "com.setu.navigator.test/androidx.test.runner.AndroidJUnitRunner"
    discovery = subprocess.run([*prefix, "-e", "log", "true", runner],
                               capture_output=True, text=True, check=True, timeout=60)
    inventory = directory / "discovery.log"
    inventory.write_text(discovery.stdout, encoding="utf-8")
    tests = read_suite(inventory)["cases"]
    if not tests or not read_suite(inventory)["runnerCompleted"]:
        raise RuntimeError("Instrumentation discovery did not complete")
    selected = [case["test"] for case in tests if not classes or
                case["test"].rsplit(".", 1)[0].split(".")[-1] in classes]
    if not selected:
        raise ValueError("No matching test classes")
    manifests = []
    for index, name in enumerate(selected):
        services = subprocess.run([str(adb), "-s", serial, "shell", "dumpsys", "activity",
                                   "services", "com.setu.navigator"], capture_output=True,
                                  text=True, check=True, timeout=20).stdout
        if "RecordingService" in services:
            raise RuntimeError("Refusing to interrupt an active recording service")
        class_name, method = name.rsplit(".", 1)
        if not re.fullmatch(r"com\.setu\.navigator\.[A-Za-z0-9_.]+", name):
            raise ValueError("Invalid test identifier")
        destination = directory / f"{index + 1:03}-{class_name.split('.')[-1]}-{method}.log"
        completed = subprocess.run([*prefix, "-e", "class", f"{class_name}#{method}", runner],
                                   capture_output=True, text=True, timeout=360)
        destination.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        result = read_suite(destination)
        manifests.append(result)
        (directory / "summary.json").write_text(json.dumps(manifests, indent=2), encoding="utf-8")
        print(f"{index + 1}/{len(selected)} {name}: {result['counts']}", flush=True)
        if completed.returncode or not result["runnerCompleted"] or len(result["cases"]) != 1:
            raise RuntimeError(f"Incomplete test execution: {name}")
    return manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--classes", nargs="*")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a new output directory to preserve previous failures")
    results = run(args.adb, args.serial, args.output, args.classes)
    print("Evidence SHA-256:", hashlib.sha256(
        (args.output / "summary.json").read_bytes()).hexdigest())
    if any(suite["counts"].get("failed", 0) or suite["counts"].get("error", 0)
           for suite in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
