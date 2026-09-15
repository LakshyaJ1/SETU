"""Inspect GPS/IMU heading observability without exporting route coordinates."""

import argparse
import json
from array import array
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.spatial.transform import Rotation

from setu.collection import reference_valid


def extract_windows(path, window_seconds=2.0):
    samples = defaultdict(lambda: array("d"))
    fixes = []
    with path.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        origin = header["startedAtNs"]
        for line in stream:
            row = json.loads(line)
            kind = row.get("type")
            if kind in ("accelerometer", "gyroscope", "game_rotation_vector"):
                width = 4 if kind == "game_rotation_vector" else 3
                values = row["values"][:width]
                if len(values) != width:
                    raise ValueError(f"Incomplete {kind}")
                samples[kind].extend([(row["tNs"] - origin) / 1e9, *values])
            elif kind == "gnss_reference" and reference_valid(row):
                speed = row["speedMps"]
                deviation = row["speedAccuracyMps"]
                stopped = speed + 2 * deviation <= .8
                bearing = row.get("bearing")
                course_sigma = row.get("bearingAccuracyDegrees")
                if not stopped and (bearing is None or course_sigma is None
                                    or not 0 <= course_sigma <= 20):
                    continue
                if deviation > 1:
                    continue
                course = np.radians(bearing if not stopped else 0)
                velocity = [0, 0] if stopped else [speed * np.sin(course), speed * np.cos(course)]
                sigma = max(.2, speed + 2 * deviation) if stopped else np.hypot(
                    max(.1, deviation), speed * np.radians(course_sigma)
                )
                fixes.append([(row["tNs"] - origin) / 1e9, *velocity, sigma])
    acceleration = np.asarray(samples["accelerometer"]).reshape(-1, 4)
    gyroscope = np.asarray(samples["gyroscope"]).reshape(-1, 4)
    orientation = np.asarray(samples["game_rotation_vector"]).reshape(-1, 5)
    for data in (acceleration, gyroscope, orientation):
        if len(data) < 2 or np.any(np.diff(data[:, 0]) <= 0):
            raise ValueError("Missing or non-monotonic sensor samples")
    rotation_indices = np.searchsorted(orientation[:, 0], gyroscope[:, 0], side="right") - 1
    acceleration_indices = np.searchsorted(acceleration[:, 0], gyroscope[:, 0]) - 1
    valid = (rotation_indices >= 0) & (acceleration_indices >= 0)
    valid &= acceleration_indices < len(acceleration) - 1
    indices = np.flatnonzero(valid)
    times = gyroscope[indices, 0]
    rotations = rotation_indices[indices]
    brackets = acceleration_indices[indices]
    valid = (times - orientation[rotations, 0] <= .1)
    valid &= acceleration[brackets + 1, 0] - acceleration[brackets, 0] <= .05
    times = times[valid]
    rotations = rotations[valid]
    interpolated = np.column_stack([
        np.interp(times, acceleration[:, 0], acceleration[:, axis]) for axis in (1, 2, 3)
    ])
    world = Rotation.from_quat(orientation[rotations, 1:]).apply(interpolated)
    integrated = cumulative_trapezoid(world[:, :2], times, axis=0, initial=0)
    gaps = np.cumsum(np.r_[0, np.diff(times) > .1])
    windows = []
    previous = None
    for fix in sorted(fixes):
        if fix[0] < times[0] or fix[0] > times[-1]:
            continue
        integral = np.array([np.interp(fix[0], times, integrated[:, axis]) for axis in (0, 1)])
        gap = gaps[min(np.searchsorted(times, fix[0]), len(gaps) - 1)]
        if previous is not None:
            before, before_integral, before_gap = previous
            duration = fix[0] - before[0]
            if duration < window_seconds:
                continue
            if duration <= window_seconds + 2 and gap == before_gap:
                windows.append([
                    fix[0], duration, *(integral - before_integral),
                    fix[1] - before[1], fix[2] - before[2], np.hypot(fix[3], before[3]),
                ])
        previous = (fix, integral, gap)
    return np.asarray(windows).reshape(-1, 7)


def summary(windows):
    inertial = np.linalg.norm(windows[:, 2:4], axis=1)
    gps = np.linalg.norm(windows[:, 4:6], axis=1)
    observable = (inertial >= 2) & (gps >= 2)
    selected = windows[observable]
    ratio = inertial[observable] / gps[observable]
    variance = (selected[:, 6] / gps[observable]) ** 2
    variance += (.25 * selected[:, 1] / inertial[observable]) ** 2
    accepted = (ratio >= .65) & (ratio <= 1.35) & (variance <= .16)
    return {
        "windows": len(windows), "velocityChangeAtLeast2Mps": int(observable.sum()),
        "passesCurrentPairGates": int(accepted.sum()),
        "inertialGpsChangeRatioP10P50P90": np.quantile(ratio, [.1, .5, .9]).tolist()
        if len(ratio) else [],
        "note": "Offline causal-rotation diagnostic; not Android callback replay or field truth.",
    }


def fit_heading(windows):
    if len(windows) < 5:
        return None
    inertial = windows[:, 2:4] / windows[:, 1, None]
    gps = windows[:, 4:6] / windows[:, 1, None]
    weights = 1 / ((windows[:, 6] / windows[:, 1]) ** 2 + .15 ** 2)
    inertial_mean = np.average(inertial, axis=0, weights=weights)
    gps_mean = np.average(gps, axis=0, weights=weights)
    centered_imu = inertial - inertial_mean
    centered_gps = gps - gps_mean
    dot = np.sum(weights * np.sum(centered_imu * centered_gps, axis=1))
    cross = np.sum(weights * (centered_imu[:, 0] * centered_gps[:, 1]
                             - centered_imu[:, 1] * centered_gps[:, 0]))
    information = np.sum(weights * np.sum(centered_imu ** 2, axis=1))
    gps_information = np.sum(weights * np.sum(centered_gps ** 2, axis=1))
    if min(information, gps_information) < 1e-8:
        return None
    yaw = np.arctan2(cross, dot)
    rotation = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
    bias = inertial_mean - rotation.T @ gps_mean
    residual = (inertial - bias) @ rotation.T - gps
    residual_scale = np.sum(weights * np.sum(residual ** 2, axis=1)) / (2 * len(windows) - 3)
    coherent_information = np.hypot(dot, cross)
    sigma = np.sqrt(np.radians(15) ** 2 + max(1, residual_scale)
                    / max(coherent_information, 1e-12))
    correlation = coherent_information / np.sqrt(information * gps_information)
    scale = np.sqrt(information / gps_information)
    return {
        "yawRadians": float(yaw), "sigmaRadians": float(sigma),
        "biasMps2": bias.tolist(), "residualScale": float(residual_scale),
        "correlation": float(correlation), "scale": float(scale),
        "accepted": bool(sigma <= .5 and np.linalg.norm(bias) <= .35
                         and .65 <= scale <= 1.35 and residual_scale <= 4),
    }


def rolling_fits(windows):
    output = []
    for index, row in enumerate(windows):
        selected = windows[:index + 1]
        selected = selected[selected[:, 0] >= row[0] - 60]
        result = fit_heading(selected)
        if result:
            halves = [fit_heading(part) for part in np.array_split(selected, 2)]
            difference = np.pi
            if all(half is not None for half in halves):
                difference = np.angle(np.exp(1j * (halves[0]["yawRadians"]
                                                   - halves[1]["yawRadians"])))
            result["accepted"] = bool(result["accepted"] and abs(difference) <= np.radians(20))
            output.append({"elapsedSeconds": float(row[0]), **result})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--interval", type=float, choices=(2, 4, 6), default=2)
    arguments = parser.parse_args()
    windows = extract_windows(arguments.recording, arguments.interval)
    if arguments.windows:
        arguments.windows.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(arguments.windows, windows=windows)
    fits = rolling_fits(windows)
    print(json.dumps({
        **summary(windows), "pooledFits": len(fits),
        "acceptedPooledFits": sum(row["accepted"] for row in fits),
        "acceptedBefore120Seconds": sum(
            row["accepted"] and row["elapsedSeconds"] < 120 for row in fits
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
