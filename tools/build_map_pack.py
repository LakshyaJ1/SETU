"""Package an existing SETU local region; does not fetch map data."""

import argparse
import gzip
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from tools.build_map_tiles import tile_index
from tools.build_road_graph import file_sha256


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
    parser.add_argument(
        "--compiled-graph", type=Path, help="Prepared graph.json and roads.bin.gzip for Android"
    )
    arguments = parser.parse_args()
    if arguments.vector_tiles and not arguments.android_assets:
        parser.error("--vector-tiles requires --android-assets")
    if arguments.compiled_graph and not arguments.android_assets:
        parser.error("--compiled-graph requires --android-assets")
    checksum = build(arguments.source, arguments.output)
    print(f"{checksum}  {arguments.output}")
    if arguments.android_assets:
        bundle_android(
            arguments.source,
            arguments.android_assets,
            arguments.vector_tiles,
            arguments.compiled_graph,
        )


def bundle_android(
    source: Path,
    destination: Path,
    vector_tiles: Path | None = None,
    compiled_graph: Path | None = None,
) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Keep source region and bundled assets separate")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = {}
    manifest["uncompressedBytes"] = {}
    manifest["compressedAssets"] = True
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("city.geojson", "roads.json"):
        manifest["sha256"][name] = file_sha256(source / name)
        manifest["uncompressedBytes"][name] = (source / name).stat().st_size
        if compiled_graph is not None and name == "roads.json":
            graph = json.loads((compiled_graph / "graph.json").read_text(encoding="utf-8"))
            if (
                graph.get("schema") != "setu.road-graph.v1"
                or graph["sourceSha256"] != manifest["sha256"][name]
            ):
                raise ValueError("Compiled graph does not match this region")
            if graph["archive"] != "roads.bin.gzip":
                raise ValueError("Unsupported graph archive")
            if file_sha256(compiled_graph / "roads.bin.gzip") != graph["archiveSha256"]:
                raise ValueError("Compiled graph archive checksum mismatch")
            for filename in ("roads.bin.gzip", "graph.json"):
                shutil.copyfile(compiled_graph / filename, destination / filename)
            (destination / "roads.json.gzip").unlink(missing_ok=True)
            continue
        if vector_tiles is not None and name == "city.geojson":
            tiles = json.loads((vector_tiles / "tiles.json").read_text(encoding="utf-8"))
            if tiles["sourceSha256"] != manifest["sha256"][name]:
                raise ValueError("Vector tiles do not match this region")
            if file_sha256(vector_tiles / "city-tiles.zip") != tiles["sha256"]:
                raise ValueError("Vector tile archive checksum mismatch")
            index = tile_index(vector_tiles / "city-tiles.zip")
            if (
                len(index["tiles"]) != tiles["tileCount"]
                or sum(tile[1] for tile in index["tiles"]) != tiles["uncompressedBytes"]
            ):
                raise ValueError("Vector tile inventory does not match metadata")
            index_bytes = (json.dumps(index, separators=(",", ":")) + "\n").encode("utf-8")
            tiles["indexSha256"] = hashlib.sha256(index_bytes).hexdigest()
            shutil.copyfile(vector_tiles / "city-tiles.zip", destination / "city-tiles.zip")
            (destination / "tile-index.json").write_bytes(index_bytes)
            (destination / "tiles.json").write_text(
                json.dumps(tiles, indent=2) + "\n", encoding="utf-8"
            )
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
    if compiled_graph is None:
        for name in ("roads.bin.gzip", "graph.json"):
            (destination / name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
