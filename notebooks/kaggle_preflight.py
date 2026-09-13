"""Read-only source inspection plus TensorFlow GPU/export smoke check on Kaggle."""
import io
import json
import pathlib
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import tensorflow as tf


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SETU-training"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


report = {
    "tensorflow": tf.__version__,
    "numpy": np.__version__,
    "gpu": [str(x) for x in tf.config.list_physical_devices("GPU")],
}
tree = json.loads(fetch("https://api.github.com/repos/onyekpeu/IO-VNBD/git/trees/master?recursive=1"))
report["data_commit"] = tree["sha"]
base = "Synchronised V abd S datasets/Uncategorised IOVNB Dataset/"
report["files"] = [x for x in tree["tree"] if x["path"].startswith(base) and x["path"].endswith(".csv")]
report["examples"] = {}
for kind in ("V", "S"):
    path = base + f"{kind}-Dataset/{kind}-S1.csv"
    url = "https://media.githubusercontent.com/media/onyekpeu/IO-VNBD/" + tree["sha"] + "/" + urllib.parse.quote(path)
    raw = fetch(url)
    frame = pd.read_csv(io.BytesIO(raw), encoding="latin-1", low_memory=False)
    report["examples"][kind] = {
        "bytes": len(raw), "shape": list(frame.shape),
        "columns": list(frame.columns), "head": frame.head(3).to_dict(orient="records"),
        "tail": frame.tail(2).to_dict(orient="records"),
        "missing": frame.isna().sum().to_dict(),
    }
pathlib.Path("preflight.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2), flush=True)
