import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools.build_map_pack import build, bundle_android
from tools.build_road_graph import compile_graph

FIXTURE = Path(__file__).resolve().parents[1] / "android/app/src/androidTest/assets/map-fixture"


def test_pack_contains_only_versioned_files_and_matching_hashes(tmp_path):
    output = tmp_path / "grid.setumap"
    checksum = build(FIXTURE, output)
    assert checksum == hashlib.sha256(output.read_bytes()).hexdigest()
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "city.geojson", "roads.json"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "setu.map.v1"
        for name in ("city.geojson", "roads.json"):
            assert manifest["sha256"][name] == hashlib.sha256(archive.read(name)).hexdigest()


def test_pack_is_reproducible_and_never_overwrites(tmp_path):
    first = tmp_path / "first.setumap"
    second = tmp_path / "second.setumap"
    assert build(FIXTURE, first) == build(FIXTURE, second)
    original = first.read_bytes()
    with pytest.raises(FileExistsError):
        build(FIXTURE, first)
    assert first.read_bytes() == original


def test_bad_manifest_creates_no_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text('{"schema":"unsupported"}', encoding="utf-8")
    output = tmp_path / "invalid.setumap"
    with pytest.raises(ValueError, match="Expected setu.map.v1"):
        build(source, output)
    assert not output.exists()


def test_bundled_assets_are_reproducible_and_match_the_source(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    bundle_android(FIXTURE, first)
    bundle_android(FIXTURE, second)
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["compressedAssets"] is True
    for name in ("city.geojson", "roads.json"):
        original = (FIXTURE / name).read_bytes()
        compressed = (first / f"{name}.gzip").read_bytes()
        assert compressed == (second / f"{name}.gzip").read_bytes()
        assert gzip.decompress(compressed) == original
        assert manifest["uncompressedBytes"][name] == len(original)
        assert manifest["sha256"][name] == hashlib.sha256(original).hexdigest()
        assert not (first / name).exists()


def test_vector_bundle_omits_the_whole_region_geojson(tmp_path):
    tiles = tmp_path / "tiles"
    tiles.mkdir()
    archive = tiles / "city-tiles.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("6/32/32.pbf", b"test tile")
    metadata = {
        "sourceSha256": hashlib.sha256((FIXTURE / "city.geojson").read_bytes()).hexdigest(),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "tileCount": 1,
        "uncompressedBytes": 9,
    }
    (tiles / "tiles.json").write_text(json.dumps(metadata), encoding="utf-8")
    destination = tmp_path / "assets"
    bundle_android(FIXTURE, destination, tiles)
    assert not (destination / "city.geojson.gzip").exists()
    assert (destination / "roads.json.gzip").is_file()
    assert (destination / "city-tiles.zip").read_bytes() == archive.read_bytes()
    index = json.loads((destination / "tile-index.json").read_bytes())
    assert index["tiles"] == [["6/32/32.pbf", 9, hashlib.sha256(b"test tile").hexdigest()]]
    bundled = json.loads((destination / "tiles.json").read_bytes())
    assert (
        bundled["indexSha256"]
        == hashlib.sha256((destination / "tile-index.json").read_bytes()).hexdigest()
    )
    metadata["sourceSha256"] = "0" * 64
    (tiles / "tiles.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match"):
        bundle_android(FIXTURE, tmp_path / "wrong", tiles)


def test_compiled_bundle_replaces_json_graph_only_when_source_and_archive_match(tmp_path):
    compiled = tmp_path / "compiled"
    metadata = compile_graph(FIXTURE / "roads.json", compiled)
    assets = tmp_path / "assets"
    bundle_android(FIXTURE, assets, compiled_graph=compiled)
    assert not (assets / "roads.json.gzip").exists()
    assert (assets / "roads.bin.gzip").read_bytes() == (compiled / "roads.bin.gzip").read_bytes()
    metadata["sourceSha256"] = "0" * 64
    (compiled / "graph.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="does not match"):
        bundle_android(FIXTURE, tmp_path / "wrong", compiled_graph=compiled)
    bundle_android(FIXTURE, assets)
    assert (assets / "roads.json.gzip").exists()
    assert not (assets / "roads.bin.gzip").exists()
    assert not (assets / "graph.json").exists()
