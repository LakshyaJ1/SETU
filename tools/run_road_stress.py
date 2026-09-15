"""Run resumable synthetic arm64 comparisons without touching private recordings."""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

REMOTE = "/data/local/tmp/setu-road-stress"
PROFILES = (
    "stationary", "smooth_cruise", "turns_and_stops", "rough_turns", "potholes_turns",
    "scooter_lean_potholes", "scooter_sensor_clipping", "rough_imu_gap", "phone_handling",
)


def battery_ready(text, maximum_temperature=42.0):
    fields = dict(re.findall(r"^\s*([^:\r\n]+):\s*([^\r\n]+)$", text, re.MULTILINE))
    level = int(fields.get("level", "-1"))
    temperature = int(fields.get("temperature", "9999")) / 10
    powered = fields.get("USB powered") == "true" or fields.get("AC powered") == "true"
    return powered and level >= 5 and temperature <= maximum_temperature, level, temperature


def validate_case(path, algorithm, duration, profile, repeats):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not rows:
        raise ValueError("Incomplete benchmark output")
    protocol = rows[0]
    expected_protocol = {
        "type": "protocol", "schema": "setu.road-stress.v1", "synthetic": True,
        "warmupSeconds": 120, "scoreHz": 10, "targetMeters": 10,
        "missingCountsAsFailure": True, "absoluteAttitudeDuringBlackout": False,
    }
    if any(protocol.get(key) != value for key, value in expected_protocol.items()):
        raise ValueError("Unrecognized benchmark protocol")
    runs = [row for row in rows if row.get("type") == "run"]
    summaries = [row for row in rows if row.get("type") == "summary"]
    if len(runs) != repeats or len(summaries) != 1:
        raise ValueError("Incomplete benchmark output")
    summary = summaries[0]
    for row in [*runs, summary]:
        if (row["algorithm"], row["durationSeconds"], row["profile"]) != (
            algorithm, duration, PROFILES[profile]
        ):
            raise ValueError("Benchmark output does not match the requested case")
    expected = duration * 10 + 1
    if {row["seed"] for row in runs} != {0xBEEF + repeat * 7919 for repeat in range(repeats)}:
        raise ValueError("Missing or duplicate seeds")
    for row in runs:
        if (row["outputs"] != expected
                or not 0 <= row["within10Meters"] <= row["available"] <= expected):
            raise ValueError("Invalid availability denominator")
        if (not math.isfinite(row["jointSuccess"])
                or abs(row["jointSuccess"] - row["within10Meters"] / expected) > 1e-7):
            raise ValueError("Success rate excludes missing predictions")
    joint = sum(row["within10Meters"] for row in runs) / (expected * repeats)
    if (summary["outputs"] != expected * repeats
            or summary["runs"] != repeats
            or summary["available"] != sum(row["available"] for row in runs)
            or not math.isfinite(summary["jointSuccess"])
            or abs(summary["jointSuccess"] - joint) > 1e-7
            or summary["releaseApproved"] is not False):
        raise ValueError("Invalid benchmark summary")
    return summary


def digest(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
        return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 21), default=5)
    parser.add_argument(
        "--algorithms", nargs="+", choices=("cv", "imu", "car"), default=["cv", "imu", "car"]
    )
    parser.add_argument(
        "--durations", nargs="+", type=int, choices=(10, 30, 60, 120, 180),
        default=[10, 30, 60, 120, 180],
    )
    parser.add_argument(
        "--profiles", nargs="+", type=int, choices=range(len(PROFILES)),
        default=list(range(len(PROFILES))),
    )
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    with (arguments.output / "runner.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return execute(arguments)


def execute(arguments):
    command = [arguments.adb, "-s", arguments.serial, "shell"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def shell(*parts):
        return subprocess.check_output(
            command + list(parts), text=True, timeout=30, creationflags=flags
        )

    binary_hash = digest(arguments.binary)
    source = Path(__file__).resolve().parents[1]
    names = ("core/test/dr_bench.cpp", "core/src/setu_engine.cpp", "core/src/setu_filter.cpp",
             "core/src/filter_state.h", "core/test/turn_speed_candidate.h",
             "core/test/turn_speed_test.cpp",
             "core/include/setu_engine.h", "core/include/setu_filter.h", "core/CMakeLists.txt")
    configuration = {
        "schema": "setu.road-stress-run.v1", "binarySha256": binary_hash,
        "sources": {name: digest(source / name) for name in names}, "repeats": arguments.repeats,
        "algorithms": sorted(set(arguments.algorithms)),
        "durations": sorted(set(arguments.durations)),
        "profiles": sorted(set(arguments.profiles)),
        "deviceModel": shell("getprop", "ro.product.model").strip(),
        "deviceIdSha256": hashlib.sha256(arguments.serial.encode()).hexdigest(),
        "androidApi": shell("getprop", "ro.build.version.sdk").strip(), "synthetic": True,
    }
    manifest_path = arguments.output / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["configuration"] != configuration:
            raise ValueError("Cannot resume with different code, device, binary or settings")
    else:
        for name in names:
            destination = arguments.output / "sources" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source / name).read_bytes())
    report = {
        "configuration": configuration, "status": "running", "cases": [], "releaseApproved": False,
    }

    def save():
        staging = manifest_path.with_suffix(".pending")
        staging.write_text(json.dumps(report, indent=2), encoding="utf-8")
        staging.replace(manifest_path)

    save()
    for algorithm in configuration["algorithms"]:
        for duration in configuration["durations"]:
            for profile in configuration["profiles"]:
                path = arguments.output / f"{algorithm}-{duration}-{profile}.jsonl"
                if not path.exists():
                    process = subprocess.run(
                        command + ["pidof", "setu_dr_bench"], capture_output=True, text=True,
                        timeout=30, creationflags=flags,
                    )
                    if process.returncode not in (0, 1):
                        raise RuntimeError("Could not check device benchmark process")
                    if process.returncode == 0:
                        report.update(status="paused", reason="Device benchmark already running")
                        save()
                        print("Paused: existing device benchmark must finish first", flush=True)
                        return 2
                    if shell("sha256sum", REMOTE + "/setu_dr_bench").split()[0] != binary_hash:
                        raise ValueError("Device executable differs from the experiment binary")
                    services = shell("dumpsys", "activity", "services", "com.setu.navigator")
                    if "RecordingService" in services:
                        report.update(status="paused", reason="User recording active")
                        save()
                        return 2
                    ready, battery, temperature = battery_ready(shell("dumpsys", "battery"))
                    if not ready:
                        report.update(
                            status="paused", reason="Battery or temperature guard",
                            battery=battery, temperatureC=temperature,
                        )
                        save()
                        print(
                            f"Paused: charge={battery}% temperature={temperature:.1f} C", flush=True
                        )
                        return 2
                    started = time.monotonic()
                    temporary = path.with_suffix(".running")
                    benchmark_command = command + [
                        REMOTE + "/setu_dr_bench", REMOTE + "/geophysics",
                        str(arguments.repeats), algorithm, str(duration), str(profile),
                    ]
                    try:
                        with (temporary.open("wb") as output,
                              path.with_suffix(".stderr").open("wb") as error):
                            result = subprocess.run(
                                benchmark_command, stdout=output, stderr=error,
                                timeout=900, creationflags=flags,
                            )
                    except subprocess.TimeoutExpired:
                        report.update(status="paused", reason="Device execution timeout")
                        save()
                        raise
                    if result.returncode not in (0, 1):
                        raise RuntimeError(
                            f"Benchmark execution failed: {path.name}; exit={result.returncode}"
                        )
                    validate_case(temporary, algorithm, duration, profile, arguments.repeats)
                    temporary.replace(path)
                    print(f"{path.name}: finished in {time.monotonic() - started:.1f}s", flush=True)
                summary = validate_case(path, algorithm, duration, profile, arguments.repeats)
                report["cases"].append({
                    "file": path.name, "sha256": digest(path), "summary": summary,
                })
                save()
    report["status"] = "completed"
    save()
    print(
        f"Completed {len(report['cases'])} conditions; synthetic, not release approval", flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
