"""Build bounded offline vector tiles from a generated region using Tippecanoe."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from tools.build_road_graph import file_sha256


def tile_index(archive: Path):
    tiles = []
    names = set()
    total = 0
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if not re.fullmatch(r"(?:[6-9]|1[0-3])/[0-9]{1,4}/[0-9]{1,4}\.pbf", entry.filename):
                raise ValueError("Invalid tile path")
            zoom, column, row = map(int, entry.filename.removesuffix(".pbf").split("/"))
            if column >= 2**zoom or row >= 2**zoom or entry.filename in names:
                raise ValueError("Invalid or duplicate tile coordinates")
            if not 0 < entry.file_size <= 500000 or len(tiles) >= 25000:
                raise ValueError("Tile archive exceeds its limits")
            total += entry.file_size
            if total > 512 * 1024 * 1024:
                raise ValueError("Tile archive exceeds its limits")
            content = source.read(entry)
            names.add(entry.filename)
            tiles.append([entry.filename, len(content), hashlib.sha256(content).hexdigest()])
    if not tiles:
        raise ValueError("Empty tile archive")
    return {
        "schema": "setu.tile-index.v1",
        "archiveSha256": file_sha256(archive),
        "tiles": sorted(tiles),
    }


def minimum_zoom(properties):
    kind = properties.get("kind")
    road = properties.get("class", "")
    if kind == "water" or road in {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
    }:
        return 6
    if road in {"secondary", "secondary_link"}:
        return 8
    if kind == "park" or road in {"tertiary", "tertiary_link"}:
        return 10
    return 12


def tile_features(features):
    for feature in features:
        geometry = feature["geometry"]
        parts = (
            geometry["coordinates"]
            if geometry["type"] == "MultiLineString"
            else [geometry["coordinates"]]
        )
        geometry_type = "LineString" if geometry["type"] == "MultiLineString" else geometry["type"]
        for part in parts:
            yield {
                "type": "Feature",
                "properties": feature["properties"],
                "geometry": {"type": geometry_type, "coordinates": part},
                "tippecanoe": {"minzoom": minimum_zoom(feature["properties"])},
            }


def build(source: Path, output: Path, tippecanoe: str):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="setu-tiles-") as temporary:
        work = Path(temporary)
        with (source / "city.geojson").open(encoding="utf-8") as original:
            document = json.load(original)
        with (work / "features.jsonl").open("w", encoding="utf-8") as stream:
            count = 0
            for feature in tile_features(document["features"]):
                stream.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
        del document
        subprocess.run(
            [
                tippecanoe,
                "--output-to-directory",
                str(work / "tiles"),
                "--layer",
                "city",
                "--minimum-zoom=6",
                "--maximum-zoom=13",
                "--no-tile-compression",
                "--no-feature-limit",
                "--maximum-tile-bytes=500000",
                "--drop-densest-as-needed",
                "--read-parallel",
                "--quiet",
                str(work / "features.jsonl"),
            ],
            check=True,
        )
        files = sorted((work / "tiles").rglob("*.pbf"))
        archive = output / "city-tiles.zip"
        maximum = 0
        total = 0
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as target:
            for path in files:
                content = path.read_bytes()
                if not 0 < len(content) <= 500000:
                    raise ValueError("Tile exceeds the bounded renderer budget")
                maximum = max(maximum, len(content))
                total += len(content)
                entry = zipfile.ZipInfo(
                    path.relative_to(work / "tiles").as_posix(), (2026, 1, 1, 0, 0, 0)
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(entry, content)
        checksum = file_sha256(archive)
        source_hash = file_sha256(source / "city.geojson")
        metadata = {
            "schema": "setu.vector-tiles.v1",
            "archive": archive.name,
            "sha256": checksum,
            "sourceSha256": source_hash,
            "minZoom": 6,
            "maxZoom": 13,
            "layer": "city",
            "tileCount": len(files),
            "maximumTileBytes": maximum,
            "uncompressedBytes": total,
            "archiveBytes": archive.stat().st_size,
            "sourceFeatures": count,
            "tippecanoeVersion": subprocess.check_output(
                [tippecanoe, "--version"], text=True, stderr=subprocess.STDOUT
            ).strip(),
        }
        (output / "tiles.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metadata, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tippecanoe", default="tippecanoe")
    arguments = parser.parse_args()
    build(arguments.source, arguments.output, arguments.tippecanoe)


if __name__ == "__main__":
    main()
