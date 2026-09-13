"""Download requested Kaggle artifacts strictly inside this notebooks directory."""
import json
import pathlib
import shutil
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
requests = json.loads((ROOT / "download_requests.json").read_text())
for item in requests:
    target = (ROOT / item["file"]).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError("Output must stay within notebooks")
    parts = urllib.parse.urlsplit(item["url"])
    if parts.scheme != "https" or not (parts.hostname or "").endswith(".kaggleusercontent.com"):
        raise ValueError("Only HTTPS Kaggle output URLs are supported")
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(item["url"], timeout=180) as response:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)
    print(f"Downloaded {target.relative_to(ROOT)}: {target.stat().st_size} bytes", flush=True)
