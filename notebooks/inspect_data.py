"""Inspect source timestamp discontinuities and yaw alignment without training."""
import io, json, pathlib, urllib.parse, urllib.request
import numpy as np
import pandas as pd

COMMIT = "118939602e3422d47b8ab0807b623751c3ac135b"
BASE = "Synchronised V abd S datasets/Uncategorised IOVNB Dataset/"
report = {}
for name in ("M", "Y1", "Vfa02"):
    records = {}
    frames = {}
    for kind in ("V", "S"):
        path = BASE + f"{kind}-Dataset/{kind}-{name}.csv"
        url = f"https://media.githubusercontent.com/media/onyekpeu/IO-VNBD/{COMMIT}/" + urllib.parse.quote(path)
        with urllib.request.urlopen(url, timeout=120) as response:
            frame = pd.read_csv(io.BytesIO(response.read()), encoding="latin-1", low_memory=False)
        frame.columns = [c.strip() for c in frame.columns]
        col = [c for c in frame if "TIME SINCE START" in c or "Time Since Start of Day" in c][0]
        t = pd.to_numeric(frame[col], errors="coerce").to_numpy()
        diff = np.diff(t)
        bad = np.flatnonzero(diff <= 0)
        records[kind] = {"rows": len(frame), "column": col, "start": float(t[0]), "end": float(t[-1]),
            "bad_count": len(bad), "nonfinite_count": int((~np.isfinite(t)).sum()),
            "diff_quantiles": np.nanpercentile(diff, [0, .1, 50, 99.9, 100]).tolist(),
            "bad_examples": [{"index": int(i), "times": t[max(0,i-2):i+4].tolist()} for i in bad[:10]]}
        numeric = frame.select_dtypes(include="number")
        records[kind]["channel_quantiles"] = {c: np.nanpercentile(numeric[c], [0, 1, 50, 99, 100]).tolist()
            for c in numeric if any(x in c.lower() for x in ("yaw", "gyro", "gravity"))}
        frames[kind] = frame
        if kind == "S":
            dates = frame[[c for c in frame if c.startswith("DATE")][0]]
            parsed = pd.to_datetime(dates, format="%Y-%m-%d %H:%M:%S:%f", errors="coerce")
            seconds = parsed.astype("int64").to_numpy() / 1e9
            records[kind]["date_diagnostics"] = {"first": str(dates.iloc[0]), "last": str(dates.iloc[-1]),
                "invalid": int(parsed.isna().sum()), "bad_count": int((np.diff(seconds)<=0).sum()),
                "diff_quantiles": np.nanpercentile(np.diff(seconds), [0,50,99,100]).tolist(),
                "reset_dates": [dates.iloc[max(0,i-1):i+3].tolist() for i in bad[:5]]}
            records[kind]["sensor_first_rows"] = frame[[c for c in frame if "ACCELEROMETER" in c or "GRAVITY" in c]].head(3).to_dict("records")
    vf, sf = frames["V"], frames["S"]
    yaw = vf[[c for c in vf if "Yaw Rate" in c][0]].to_numpy()
    n = min(len(vf), len(sf))
    records["raw_axis_correlations"] = {}
    for c in sf:
        if "GYROSCOPE" in c:
            g = sf[c].to_numpy()[:n]
            ok = np.isfinite(g) & np.isfinite(yaw[:n]) & (np.abs(yaw[:n]) < 90) & (np.abs(g) < 2)
            records["raw_axis_correlations"][c] = float(np.corrcoef(g[ok], yaw[:n][ok])[0,1])
    report[name] = records
pathlib.Path("data_diagnostics.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
