"""Reproducible IO-VNBD ingest for the SETU notebook; no synthetic fallback."""
import concurrent.futures
import hashlib
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

DATA_COMMIT = "118939602e3422d47b8ab0807b623751c3ac135b"
DATA_PREFIX = "Synchronised V abd S datasets/Uncategorised IOVNB Dataset/"


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SETU-training"})
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def acquire_data(root):
    root.mkdir(parents=True, exist_ok=True)
    tree = json.loads(fetch(f"https://api.github.com/repos/onyekpeu/IO-VNBD/git/trees/{DATA_COMMIT}?recursive=1"))
    paths = [x["path"] for x in tree["tree"] if x["path"].startswith(DATA_PREFIX) and x["path"].endswith(".csv")]
    by_kind = {kind: {pathlib.PurePosixPath(p).stem[2:].lower(): p for p in paths
                     if f"/{kind}-Dataset/" in p} for kind in ("V", "S")}
    names = sorted(by_kind["V"].keys() & by_kind["S"].keys())

    def download(item):
        kind, name = item
        path = by_kind[kind][name]
        encoded = urllib.parse.quote(path)
        pointer = fetch(f"https://raw.githubusercontent.com/onyekpeu/IO-VNBD/{DATA_COMMIT}/{encoded}").decode()
        digest = re.search(r"oid sha256:([0-9a-f]{64})", pointer).group(1)
        size = int(re.search(r"size (\d+)", pointer).group(1))
        destination = root / f"{kind}-{name}.csv"
        if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raw = fetch(f"https://media.githubusercontent.com/media/onyekpeu/IO-VNBD/{DATA_COMMIT}/{encoded}")
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError(f"Git LFS hash/size mismatch: {path}")
            destination.write_bytes(raw)
        return {"path": path, "sha256": digest, "bytes": size, "file": destination.name}

    jobs = [(kind, name) for name in names for kind in ("V", "S")]
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for record in pool.map(download, jobs):
            records.append(record)
            if len(records) % 12 == 0:
                print(f"Verified {len(records)}/{len(jobs)} data files", flush=True)
    return names, {"repository": "https://github.com/onyekpeu/IO-VNBD", "commit": DATA_COMMIT, "files": records}


def normalise(name):
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")


def column(frame, prefix):
    matches = [c for c in frame if c == prefix or c.startswith(prefix + "_")]
    if len(matches) != 1:
        raise ValueError(f"Expected one column for {prefix}, found {matches}")
    return pd.to_numeric(frame[matches[0]], errors="coerce").to_numpy(dtype=np.float64)


def load_pair(root, name):
    v = pd.read_csv(root / f"V-{name}.csv", encoding="latin-1", low_memory=False)
    s = pd.read_csv(root / f"S-{name}.csv", encoding="latin-1", low_memory=False)
    v.columns = [normalise(c) for c in v]
    s.columns = [normalise(c) for c in s]
    wheel = np.mean([column(v, f"wheel_speed_{ax}") for ax in
                     ("front_left", "front_right", "rear_left", "rear_right")], axis=0)
    gps = column(v, "velocity") / 3.6
    sats = column(v, "no_of_gps_satellites_available")
    # Fit rolling radius using steady, moving GPS reference epochs. This calibrates labels;
    # neither GPS nor wheels are model inputs. Implausible satellite-count encodings are excluded.
    valid = (wheel > 15) & (gps > 5) & (sats >= 6) & (sats <= 40)
    valid &= np.isfinite(wheel) & np.isfinite(gps) & (np.abs(np.gradient(gps, .1)) < .5)
    ratio = gps / np.maximum(wheel, 1e-6)
    valid &= (ratio > .20) & (ratio < .40)
    if valid.sum() < 20:
        raise ValueError("Insufficient reliable GPS epochs for rolling-radius calibration")
    radius = float(np.median(ratio[valid]))
    inlier = valid & (np.abs(ratio - radius) < .015)
    radius = float(np.dot(wheel[inlier], gps[inlier]) / np.dot(wheel[inlier], wheel[inlier]))
    speed = wheel * radius

    accel = np.stack([column(s, f"accelerometer_{ax}") for ax in "xyz"], axis=1)
    gyro = np.stack([column(s, f"gyroscope_{ax}") for ax in "xyz"], axis=1)
    gravity = np.stack([column(s, f"gravity_{ax}") for ax in "xyz"], axis=1)
    imu = np.concatenate([accel, gyro], axis=1)
    elapsed = column(s, "time_since_start") / 1000
    date_col = [c for c in s if c.startswith("date_")]
    if len(date_col) != 1:
        raise ValueError("Missing unambiguous wall-clock timestamp column")
    dates = pd.to_datetime(s[date_col[0]], format="%Y-%m-%d %H:%M:%S:%f", errors="coerce")
    if dates.isna().any():
        raise ValueError("Unparseable phone wall-clock timestamps")
    ts = (dates.astype("int64").to_numpy() - dates.astype("int64").iloc[0]) / 1e9
    tv = column(v, "time_since_start_of_day")
    tv -= tv[0]
    if np.any(np.diff(ts) <= 0):
        raise ValueError("Non-increasing phone wall-clock timestamps")
    if not np.all(np.isfinite(imu)):
        raise ValueError("Non-finite IMU samples")
    # Use the correspondence in the publisher's synchronized row pairs. Phone elapsed
    # counters reset, and the two loggers' pauses differ, so subtracting their first
    # timestamp and interpolating globally silently shifts whole sections of labels.
    # Refuse unequal pairs rather than assuming their leading rows correspond.
    if len(v) != len(s):
        raise ValueError(f"Unequal synchronized row counts ({len(v)} vs {len(s)}); needs separate alignment")
    lat_v, lon_v = column(v, "latitude"), column(v, "longitude")
    lat_s, lon_s = column(s, "gps_latitude"), column(s, "gps_longitude")
    separation = 6371000 * np.sqrt(np.deg2rad(lat_v-lat_s)**2 +
        (np.cos(np.deg2rad(lat_v))*np.deg2rad(lon_v-lon_s))**2)
    finite_sep = np.isfinite(separation) & (np.abs(lat_v) < 90) & (np.abs(lat_s) < 90)
    median_sep = float(np.median(separation[finite_sep]))
    if not np.isfinite(median_sep) or median_sep > 50:
        raise ValueError(f"Published row alignment fails GPS position cross-check: median {median_sep:.1f} m")
    labels = speed
    valid = np.isfinite(labels) & (labels >= 0) & (labels <= 45)
    valid &= finite_sep & (separation <= 100)
    # Exclude windows that cross either logger's discontinuity, including duplicate
    # vehicle timestamps, rather than joining disconnected pieces of driving.
    vehicle_break = np.r_[False, (np.diff(tv) <= 0) | (np.diff(tv) > .2)]
    valid &= ~vehicle_break
    valid &= (np.max(np.abs(accel), axis=1) < 78) & (np.max(np.abs(gyro), axis=1) < 16)
    report = {"run": name, "rows": len(ts), "duration_s": float(ts[-1]), "wheel_radius_m": radius,
              "radius_calibration_epochs": int(inlier.sum()), "alignment": "publisher synchronized row correspondence; GPS position cross-check",
              "gps_alignment_median_m": median_sep, "gps_alignment_p90_m": float(np.percentile(separation[finite_sep], 90)),
              "elapsed_counter_resets": int((np.diff(elapsed)<=0).sum()), "vehicle_time_breaks": int(vehicle_break.sum()),
              "median_rate_hz": float(1 / np.median(np.diff(ts))),
              "invalid_samples": int((~valid).sum()), "max_gap_s": float(np.max(np.diff(ts)))}
    return {"name": name, "time": ts, "imu": imu.astype(np.float32), "speed": labels.astype(np.float32),
            "valid": valid, "report": report}


def window_runs(runs, window=400, rate=100, hop_s=1.0):
    windows, labels, metadata = [], [], []
    for run in runs:
        t, imu, speed = run["time"], run["imu"], run["speed"]
        duration = (window - 1) / rate
        for end in np.arange(duration, t[-1], hop_s):
            grid = end - np.arange(window - 1, -1, -1) / rate
            lo = max(0, np.searchsorted(t, grid[0], side="right") - 1)
            hi = min(len(t), np.searchsorted(t, grid[-1], side="left") + 1)
            if hi - lo < 30 or not np.all(run["valid"][lo:hi]) or np.max(np.diff(t[lo:hi])) > .2:
                continue
            x = np.stack([np.interp(grid, t[lo:hi], imu[lo:hi, c]) for c in range(6)], axis=1)
            windows.append(x.astype(np.float32))
            labels.append(np.interp(end, t, speed))
            metadata.append((run["name"], float(end)))
    if not windows:
        raise ValueError("No valid windows in split")
    return np.asarray(windows), np.asarray(labels, np.float32), metadata
