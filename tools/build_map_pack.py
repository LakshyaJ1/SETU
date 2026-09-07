"""Package an existing SETU local region; does not fetch map data."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def build(source: Path, output: Path) -> str:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "setu.map.v1":
        raise ValueError("Expected setu.map.v1 manifest")
    files = {name: (source / name).read_bytes() for name in ("city.geojson", "roads.json")}
    manifest["sha256"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    limits = {"manifest.json": 65536, "city.geojson": 24 * 1024**2, "roads.json": 8 * 1024**2}
    for name, content in files.items():
        if not 0 < len(content) <= limits[name]:
            raise ValueError(f"Missing or oversized {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing manifest.json, city.geojson and roads.json")
    parser.add_argument("output", type=Path, help="New .setumap file (existing files are not overwritten)")
    arguments = parser.parse_args()
    checksum = build(arguments.source, arguments.output)
    print(f"{checksum}  {arguments.output}")


if __name__ == "__main__":
    main()
