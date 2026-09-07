import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from tools.build_map_pack import build


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
