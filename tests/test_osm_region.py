import json
from pathlib import Path

import pytest

from tools.build_osm_region import (
    compact_region,
    convert,
    drivable,
    inside,
    map_name,
    simplify_indices,
    way_data,
)

BOUNDS = [28.39, 76.83, 28.91, 77.36]
COORDINATES = [[77.21, 28.63], [77.22, 28.64], [77.23, 28.65]]


def test_extent_covers_outer_delhi_but_not_unrelated_cities():
    for point in ([76.84, 28.60], [77.10, 28.89], [77.33, 28.62], [77.20, 28.40]):
        assert inside(point, BOUNDS)
    assert not inside([77.60, 12.97], BOUNDS)
    assert not inside([77.5, 28.63], BOUNDS)


def test_roads_keep_shared_nodes_coordinates_and_direction():
    feature, road = way_data(
        42,
        [101, 102, 103],
        COORDINATES,
        {"highway": "residential", "name": "Test Road", "oneway": "-1"},
        BOUNDS,
        {0},
    )
    assert feature["geometry"]["coordinates"] == road["coordinates"] == COORDINATES
    assert road["nodes"] == [101, 102, 103]
    assert road["oneway"] == "-1"
    assert road["name"] == "Test Road"
    assert road["id"] == 42


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "footway"},
        {"highway": "residential", "access": "private"},
        {"highway": "service", "motor_vehicle": "no"},
        {"highway": "primary", "motorcar": "forestry"},
    ],
)
def test_non_drivable_roads_remain_visible_without_entering_graph(tags):
    feature, road = way_data(42, [101, 102, 103], COORDINATES, tags, BOUNDS, {0})
    assert feature is not None
    assert road is None


def test_specific_access_and_roundabout_defaults():
    tags = {"highway": "residential", "access": "private", "motor_vehicle": "yes"}
    assert drivable(tags)
    _, road = way_data(
        42,
        [101, 102, 103],
        COORDINATES,
        {"highway": "primary", "junction": "roundabout"},
        BOUNDS,
        {0},
    )
    assert road["oneway"] == "yes"
    _, reversible = way_data(
        42,
        [101, 102, 103],
        COORDINATES,
        {"highway": "primary", "oneway": "reversible"},
        BOUNDS,
        {0},
    )
    assert reversible is None


def test_area_rings_must_close_and_outside_ways_are_excluded():
    assert way_data(42, [1, 2, 3], COORDINATES, {"leisure": "park"}, BOUNDS, {0}) == (None, None)
    ring = [*COORDINATES, COORDINATES[0]]
    feature, road = way_data(42, [1, 2, 3, 1], ring, {"leisure": "park"}, BOUNDS, {0})
    assert feature["geometry"] == {"type": "Polygon", "coordinates": [ring]}
    assert road is None
    assert way_data(
        42, [1, 2], [[76.0, 28.0], [76.1, 28.1]], {"highway": "primary"}, BOUNDS, {0}
    ) == (None, None)


def test_labels_use_available_offline_glyphs_without_faking_transliteration():
    assert map_name({"name:en": "Delhi", "name": "दिल्ली"}, {0}) == "Delhi"
    assert map_name({"name": "दिल्ली"}, {0}) == ""
    assert map_name({"name": "दिल्ली"}, {2304}) == "दिल्ली"


def test_pbf_filter_preserves_untagged_geometry_nodes_and_source_timestamp(tmp_path):
    osmium = pytest.importorskip("osmium")
    source = tmp_path / "source.osm.pbf"
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", "2026-09-06T20:21:35Z")
    with osmium.SimpleWriter(str(source), header=header) as writer:
        for identifier, point in zip([101, 102, 103], COORDINATES, strict=True):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=tuple(point)))
        writer.add_way(
            osmium.osm.mutable.Way(
                id=42, nodes=[101, 102, 103], tags={"highway": "primary", "name": "Test Road"}
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=43, nodes=[102, 103], tags={"highway": "secondary", "name": "Connector"}
            )
        )
    glyphs = tmp_path / "glyphs"
    glyphs.mkdir()
    (glyphs / "0-255.pbf").touch()
    configuration = Path(__file__).resolve().parents[1] / "tools/map-regions/delhi.json"
    output = tmp_path / "region"
    summary = convert(source, configuration, output, glyphs)
    assert summary["features"] == summary["routableWays"] == 2
    assert summary["dataTimestamp"] == "2026-09-06T20:21:35Z"
    road = json.loads((output / "roads.json").read_text(encoding="utf-8"))["roads"][0]
    assert road["nodes"] == [101, 102, 103]
    assert road["coordinates"] == COORDINATES


def test_compaction_keeps_all_streets_but_only_declared_routing_classes():
    residential, local_road = way_data(
        1, [1, 2, 3], COORDINATES, {"highway": "residential"}, BOUNDS, {0}
    )
    main, main_road = way_data(
        2, [1, 2, 3], COORDINATES, {"highway": "primary", "oneway": "-1"}, BOUNDS, {0}
    )
    junction, branch = way_data(
        3, [2, 4], [COORDINATES[1], [77.23, 28.64]], {"highway": "primary"}, BOUNDS, {0}
    )
    features, graph = compact_region([residential, main, junction], [local_road, main_road, branch])
    assert sum(len(feature["geometry"]["coordinates"]) for feature in features) == 3
    assert {feature["properties"]["class"] for feature in features} == {"residential", "primary"}
    assert [road["id"] for road in graph] == [2, 3]
    assert graph[0]["nodes"] == [1, 2, 3]
    assert graph[0]["oneway"] == "-1"
    assert graph[0]["coordinates"][1] == graph[1]["coordinates"][0]


def test_simplification_preserves_endpoints_bends_and_pinned_junctions():
    assert simplify_indices(COORDINATES) == [0, 2]
    assert simplify_indices(COORDINATES, pinned=[1]) == [0, 1, 2]
    assert simplify_indices([[77.21, 28.63], [77.22, 28.63], [77.22, 28.64]]) == [0, 1, 2]


def test_ncr_configuration_includes_satellite_cities_and_local_routing():
    configuration = Path(__file__).resolve().parents[1] / "tools/map-regions/delhi-ncr.json"
    manifest = json.loads(configuration.read_text(encoding="utf-8"))
    for point in (
        [77.03, 28.46],
        [77.39, 28.54],
        [77.45, 28.67],
        [76.99, 29.69],
        [76.63, 27.55],
        [77.49, 27.22],
    ):
        assert inside(point, manifest["bounds"])
    assert not inside([77.60, 12.97], manifest["bounds"])
    assert {"residential", "service", "living_street"} <= set(manifest["routingClasses"])
    assert manifest["indexedNodes"]
    assert manifest["routingToleranceMeters"] == 5.0
    assert manifest["drawingToleranceMeters"] == 3.0
    assert manifest["demoDestination"] == "mait-rohini"


def test_full_routing_keeps_local_streets_and_chunks_large_draw_groups():
    feature, road = way_data(
        42, [101, 102, 103], COORDINATES, {"highway": "residential"}, BOUNDS, {0}
    )
    features, roads = compact_region([feature] * 600, [road], {"residential"})
    assert len(features) == 3
    assert sum(len(feature["geometry"]["coordinates"]) for feature in features) == 600
    assert len(roads) == 1


def test_multiple_extracts_deduplicate_roads_and_emit_indexed_topology(tmp_path):
    osmium = pytest.importorskip("osmium")
    source = tmp_path / "source.osm.pbf"
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", "2026-09-06T20:21:35Z")
    with osmium.SimpleWriter(str(source), header=header) as writer:
        for identifier, point in zip([101, 102, 103], COORDINATES, strict=True):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=tuple(point)))
        writer.add_way(
            osmium.osm.mutable.Way(id=42, nodes=[101, 102, 103], tags={"highway": "residential"})
        )
    glyphs = tmp_path / "glyphs"
    glyphs.mkdir()
    (glyphs / "0-255.pbf").touch()
    configuration = Path(__file__).resolve().parents[1] / "tools/map-regions/delhi-ncr.json"
    output = tmp_path / "region"
    summary = convert(source, configuration, output, glyphs, [source])
    graph = json.loads((output / "roads.json").read_text(encoding="utf-8"))
    assert summary["routableWays"] == 1
    assert len(summary["sources"]) == 2
    assert graph["nodeCount"] == 2
    assert graph["edgeCount"] == 2
    assert graph["roads"][0]["nodes"] == [1, 2]
    assert graph["roads"][0]["coordinates"] == [COORDINATES[0], COORDINATES[-1]]
