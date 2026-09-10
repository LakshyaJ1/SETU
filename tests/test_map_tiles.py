import hashlib
import zipfile

import pytest

from tools.build_map_tiles import minimum_zoom, tile_features, tile_index


def test_tile_index_is_deterministic_and_hashes_each_payload(tmp_path):
    archive = tmp_path / "tiles.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("13/5852/3415.pbf", b"detail")
        output.writestr("6/45/26.pbf", b"overview")
    index = tile_index(archive)
    assert index == tile_index(archive)
    assert index["archiveSha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert index["tiles"] == [
        ["13/5852/3415.pbf", 6, hashlib.sha256(b"detail").hexdigest()],
        ["6/45/26.pbf", 8, hashlib.sha256(b"overview").hexdigest()],
    ]


@pytest.mark.parametrize(
    "name,payload",
    [("../tile.pbf", b"a"), ("6/64/0.pbf", b"a"), ("6/0/0.pbf", b""), ("6/0/0.pbf", b"a" * 500001)],
    ids=["path", "coordinates", "empty", "oversized"],
)
def test_tile_index_rejects_unsafe_paths_and_payloads(tmp_path, name, payload):
    archive = tmp_path / "tiles.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(name, payload)
    with pytest.raises(ValueError):
        tile_index(archive)


def test_tiles_split_disconnected_road_groups_and_preserve_properties():
    properties = {"kind": "road", "class": "residential", "name": "Local street"}
    lines = [[[77.1, 28.6], [77.2, 28.6]], [[77.3, 28.7], [77.4, 28.7]]]
    features = list(
        tile_features(
            [
                {
                    "properties": properties,
                    "geometry": {"type": "MultiLineString", "coordinates": lines},
                }
            ]
        )
    )
    assert len(features) == 2
    for feature, line in zip(features, lines, strict=True):
        assert feature["properties"] == properties
        assert feature["geometry"] == {"type": "LineString", "coordinates": line}
        assert feature["tippecanoe"]["minzoom"] == 12


def test_overview_keeps_arteries_and_water_not_every_local_street():
    assert minimum_zoom({"kind": "water"}) == 6
    assert minimum_zoom({"kind": "road", "class": "primary"}) == 6
    assert minimum_zoom({"kind": "road", "class": "secondary"}) == 8
    assert minimum_zoom({"kind": "park"}) == 10
    assert minimum_zoom({"kind": "road", "class": "service"}) == 12
