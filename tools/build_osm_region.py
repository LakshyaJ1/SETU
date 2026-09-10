"""Build a local SETU map from a downloaded OSM PBF; never downloads data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from tools.build_android_region import DRIVABLE
from tools.build_map_pack import build

ROUTE_CLASSES = DRIVABLE - {"residential", "service", "living_street"}


def simplify_indices(coordinates, tolerance=1.0, pinned=()):
    if len(coordinates) <= 2:
        return list(range(len(coordinates)))
    scale = math.cos(math.radians(coordinates[0][1]))
    points = [(point[0] * 111320 * scale, point[1] * 111320) for point in coordinates]
    retained = {0, len(points) - 1, *pinned}
    anchors = sorted(retained)
    pending = list(zip(anchors, anchors[1:], strict=False))
    while pending:
        start, end = pending.pop()
        horizontal = points[end][0] - points[start][0]
        vertical = points[end][1] - points[start][1]
        length = horizontal * horizontal + vertical * vertical
        farthest, distance = None, tolerance * tolerance
        for index in range(start + 1, end):
            fraction = (
                0
                if length == 0
                else max(
                    0,
                    min(
                        1,
                        (
                            (points[index][0] - points[start][0]) * horizontal
                            + (points[index][1] - points[start][1]) * vertical
                        )
                        / length,
                    ),
                )
            )
            deviation = (points[index][0] - points[start][0] - fraction * horizontal) ** 2 + (
                points[index][1] - points[start][1] - fraction * vertical
            ) ** 2
            if deviation > distance:
                farthest, distance = index, deviation
        if farthest is not None:
            retained.add(farthest)
            pending.extend(((start, farthest), (farthest, end)))
    return sorted(retained)


def compact_region(
    features, roads, routing_classes=ROUTE_CLASSES, routing_tolerance=1.0, drawing_tolerance=1.0
):
    groups = {}
    compacted = []
    for feature in features:
        properties = feature["properties"]
        if properties["kind"] != "road":
            compacted.append(feature)
            continue
        coordinates = feature["geometry"]["coordinates"]
        line = [
            coordinates[index]
            for index in simplify_indices(coordinates, tolerance=drawing_tolerance)
        ]
        key = properties["class"], properties["name"]
        groups.setdefault(key, []).append(line)
    for (road_class, name), lines in groups.items():
        for offset in range(0, len(lines), 256):
            compacted.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "road", "class": road_class, "name": name},
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": lines[offset : offset + 256],
                    },
                }
            )
    selected = [road for road in roads if road["class"] in routing_classes]
    occurrences = Counter(node for road in selected for node in set(road["nodes"]))
    graph = []
    for road in selected:
        pinned = [index for index, node in enumerate(road["nodes"]) if occurrences[node] > 1]
        indices = simplify_indices(road["coordinates"], tolerance=routing_tolerance, pinned=pinned)
        graph.append(
            {
                **road,
                "nodes": [road["nodes"][index] for index in indices],
                "coordinates": [road["coordinates"][index] for index in indices],
            }
        )
    return compacted, graph


def inside(point, bounds):
    return bounds[1] <= point[0] <= bounds[3] and bounds[0] <= point[1] <= bounds[2]


def map_name(tags, glyph_ranges):
    for key in ("name:en", "int_name", "name"):
        name = tags.get(key, "")
        if (
            name
            and len(name) <= 200
            and all(ord(character) // 256 * 256 in glyph_ranges for character in name)
        ):
            return name
    return ""


def drivable(tags):
    access = tags.get(
        "motorcar", tags.get("motor_vehicle", tags.get("vehicle", tags.get("access", "yes")))
    )
    return tags.get("highway") in DRIVABLE and access not in {
        "private",
        "no",
        "agricultural",
        "forestry",
    }


def way_data(identifier, node_ids, coordinates, tags, bounds, glyph_ranges):
    if len(coordinates) < 2 or not any(inside(point, bounds) for point in coordinates):
        return None, None
    highway = tags.get("highway")
    kind = (
        "road"
        if highway
        else (
            "park"
            if tags.get("leisure") in {"park", "garden", "nature_reserve"}
            else "water"
            if tags.get("natural") == "water" or tags.get("waterway") == "riverbank"
            else None
        )
    )
    if (
        kind is None
        or kind != "road"
        and (len(coordinates) < 4 or coordinates[0] != coordinates[-1])
    ):
        return None, None
    name = map_name(tags, glyph_ranges)
    feature = {
        "type": "Feature",
        "properties": {"kind": kind, "class": highway or kind, "name": name},
        "geometry": {
            "type": "LineString" if kind == "road" else "Polygon",
            "coordinates": coordinates if kind == "road" else [coordinates],
        },
    }
    road = None
    if drivable(tags):
        oneway = tags.get("oneway", "yes" if tags.get("junction") == "roundabout" else "no")
        if oneway not in {"no", "yes", "1", "true", "-1"}:
            return feature, None
        road = {
            "id": identifier,
            "nodes": node_ids,
            "coordinates": coordinates,
            "name": name or "Local road",
            "oneway": oneway,
            "class": highway,
        }
    return feature, road


def convert(source, configuration, output, glyph_directory, additional_sources=()):
    import osmium

    manifest = json.loads(configuration.read_text(encoding="utf-8"))
    if output.exists():
        raise FileExistsError(output)
    bounds = manifest["bounds"]
    routing_classes = set(manifest.pop("routingClasses", ROUTE_CLASSES))
    if not routing_classes or not routing_classes <= DRIVABLE:
        raise ValueError("Routing classes must be public driving-road classes")
    indexed_nodes = manifest.pop("indexedNodes", False)
    routing_tolerance = float(manifest.pop("routingToleranceMeters", 1.0))
    drawing_tolerance = float(manifest.pop("drawingToleranceMeters", 1.0))
    if not 0 < routing_tolerance <= 5 or not 0 < drawing_tolerance <= 5:
        raise ValueError("Map simplification must be within five metres")
    glyph_ranges = {int(path.stem.split("-")[0]) for path in glyph_directory.glob("*.pbf")}
    features = []
    roads = []
    places = []
    seen_ways = set()

    class RegionReader(osmium.SimpleHandler):
        def node(self, node):
            if not node.tags:
                return
            tags = dict(node.tags)
            if tags.get("railway") not in {"station", "halt", "subway_entrance"} and tags.get(
                "place"
            ) not in {"city", "suburb", "town", "neighbourhood"}:
                return
            point = [round(node.location.lon, 7), round(node.location.lat, 7)]
            name = map_name(tags, glyph_ranges)
            if name and inside(point, bounds):
                places.append(
                    {
                        "id": f"osm-node-{node.id}",
                        "name": name[:100],
                        "detail": "OSM station"
                        if "railway" in tags
                        else f"OSM {tags.get('place', 'locality')}",
                        "point": point,
                    }
                )

        def way(self, way):
            if way.id in seen_ways:
                return
            tags = dict(way.tags)
            if not (
                "highway" in tags
                or tags.get("leisure") in {"park", "garden", "nature_reserve"}
                or tags.get("natural") == "water"
                or tags.get("waterway") == "riverbank"
            ):
                return
            if any(not node.location.valid() for node in way.nodes):
                return
            coordinates = [[round(node.lon, 7), round(node.lat, 7)] for node in way.nodes]
            feature, road = way_data(
                way.id, [node.ref for node in way.nodes], coordinates, tags, bounds, glyph_ranges
            )
            if feature is not None:
                seen_ways.add(way.id)
                features.append(feature)
            if road is not None:
                roads.append(road)

    sources = []
    for source_path in (source, *additional_sources):
        with osmium.io.Reader(str(source_path)) as reader:
            timestamp = reader.header().get("osmosis_replication_timestamp")
        if not timestamp:
            raise ValueError("The OSM source must supply its data timestamp")
        with source_path.open("rb") as source_file:
            checksum = hashlib.file_digest(source_file, "sha256").hexdigest()
        sources.append({"file": source_path.name, "dataTimestamp": timestamp, "sha256": checksum})
        RegionReader().apply_file(
            str(source_path),
            locations=True,
            idx="flex_mem",
            filters=[
                osmium.filter.KeyFilter(
                    "highway", "leisure", "natural", "waterway", "place", "railway"
                )
            ],
        )
    timestamp = min(item["dataTimestamp"] for item in sources)
    seen_names = {place["name"].casefold() for place in manifest["places"]}
    priority = {"OSM city": 0, "OSM town": 1, "OSM suburb": 2, "OSM neighbourhood": 3}
    for place in sorted(
        places, key=lambda item: (priority.get(item["detail"], 4), item["name"], item["id"])
    ):
        if place["name"].casefold() not in seen_names and len(manifest["places"]) < 300:
            manifest["places"].append(place)
            seen_names.add(place["name"].casefold())
    manifest["dataTimestamp"] = timestamp
    output.mkdir(parents=True, exist_ok=False)
    raw_feature_count, raw_road_count = len(features), len(roads)
    road_classes = Counter(
        feature["properties"]["class"]
        for feature in features
        if feature["properties"]["kind"] == "road"
    )
    features, roads = compact_region(
        features, roads, routing_classes, routing_tolerance, drawing_tolerance
    )
    graph_metadata = {}
    if indexed_nodes:
        indices = {
            identifier: index + 1
            for index, identifier in enumerate(
                sorted({node for road in roads for node in road["nodes"]})
            )
        }
        for road in roads:
            road["nodes"] = [indices[node] for node in road["nodes"]]
        graph_metadata = {
            "nodeCount": len(indices),
            "edgeCount": sum(
                (len(road["nodes"]) - 1) * (2 if road["oneway"] == "no" else 1) for road in roads
            ),
        }
    documents = {
        "manifest.json": manifest,
        "city.geojson": {"type": "FeatureCollection", "features": features},
        "roads.json": {"bounds": bounds, **graph_metadata, "roads": roads},
    }
    for name, document in documents.items():
        (output / name).write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    summary = {
        "source": source.name,
        "sources": sources,
        "dataTimestamp": timestamp,
        "features": len(features),
        "sourceFeatures": raw_feature_count,
        "sourceDrivableWays": raw_road_count,
        "roadClasses": dict(road_classes),
        "geometryToleranceMeters": drawing_tolerance,
        "routingToleranceMeters": routing_tolerance,
        "routingClasses": sorted(routing_classes),
        "routableWays": len(roads),
        "nodeReferences": sum(len(road["nodes"]) for road in roads),
        "places": len(manifest["places"]),
        "visualCoordinates": sum(
            sum(len(part) for part in feature["geometry"]["coordinates"]) for feature in features
        ),
        "visualRoadSegments": sum(
            len(feature["geometry"]["coordinates"])
            for feature in features
            if feature["properties"]["kind"] == "road"
        ),
        "bytes": {name: (output / name).stat().st_size for name in documents},
    }
    summary["sourceSha256"] = sources[0]["sha256"]
    (output / "build-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("output", type=Path, help="New directory for generated region files")
    parser.add_argument("--pack", type=Path, help="Optional new .setumap archive")
    parser.add_argument("--additional-source", type=Path, action="append", default=[])
    parser.add_argument(
        "--glyph-directory",
        type=Path,
        default=Path("android/app/src/main/assets/fonts/Noto Sans Regular"),
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            convert(
                arguments.source,
                arguments.configuration,
                arguments.output,
                arguments.glyph_directory,
                arguments.additional_source,
            ),
            indent=2,
        )
    )
    if arguments.pack:
        print(f"{build(arguments.output, arguments.pack)}  {arguments.pack}")


if __name__ == "__main__":
    main()
