"""Package an existing SETU local region; does not fetch map data."""

import argparse
import gzip
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


def build(source: Path, output: Path) -> str:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "setu.map.v1":
        raise ValueError("Expected setu.map.v1 manifest")
    files = {name: (source / name).read_bytes() for name in ("city.geojson", "roads.json")}
    manifest["sha256"] = {
        name: hashlib.sha256(content).hexdigest() for name, content in files.items()
    }
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    limits = {"manifest.json": 65536, "city.geojson": 160 * 1024**2, "roads.json": 256 * 1024**2}
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
    parser.add_argument(
        "source", type=Path, help="Directory containing manifest.json, city.geojson and roads.json"
    )
    parser.add_argument(
        "output", type=Path, help="New .setumap file (existing files are not overwritten)"
    )
    parser.add_argument(
        "--android-assets",
        type=Path,
        help="Also replace generated Android map assets with deterministic gzip files",
    )
    parser.add_argument(
        "--vector-tiles",
        type=Path,
        help="Prepared city-tiles.zip and tiles.json for the Android bundle",
    )
    arguments = parser.parse_args()
    if arguments.vector_tiles and not arguments.android_assets:
        parser.error("--vector-tiles requires --android-assets")
    checksum = build(arguments.source, arguments.output)
    print(f"{checksum}  {arguments.output}")
    if arguments.android_assets:
        bundle_android(arguments.source, arguments.android_assets, arguments.vector_tiles)


def bundle_android(source: Path, destination: Path, vector_tiles: Path | None = None) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Keep source region and bundled assets separate")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = {}
    manifest["uncompressedBytes"] = {}
    manifest["compressedAssets"] = True
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("city.geojson", "roads.json"):
        with (source / name).open("rb") as original:
            manifest["sha256"][name] = hashlib.file_digest(original, "sha256").hexdigest()
        manifest["uncompressedBytes"][name] = (source / name).stat().st_size
        if vector_tiles is not None and name == "city.geojson":
            tiles = json.loads((vector_tiles / "tiles.json").read_text(encoding="utf-8"))
            if tiles["sourceSha256"] != manifest["sha256"][name]:
                raise ValueError("Vector tiles do not match this region")
            with (vector_tiles / "city-tiles.zip").open("rb") as archive:
                if hashlib.file_digest(archive, "sha256").hexdigest() != tiles["sha256"]:
                    raise ValueError("Vector tile archive checksum mismatch")
            for filename in ("city-tiles.zip", "tiles.json"):
                shutil.copyfile(vector_tiles / filename, destination / filename)
            (destination / f"{name}.gzip").unlink(missing_ok=True)
            continue
        with (
            (source / name).open("rb") as original,
            (destination / f"{name}.gzip").open("wb") as target,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=target, mtime=0, compresslevel=6
            ) as compressed,
        ):
            shutil.copyfileobj(original, compressed)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in ("city.geojson", "roads.json"):
        (destination / name).unlink(missing_ok=True)
        (destination / f"{name}.gz").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
