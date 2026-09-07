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


def compact_region(features, roads):
    groups = {}
    compacted = []
    for feature in features:
        properties = feature["properties"]
        if properties["kind"] != "road":
            compacted.append(feature)
            continue
        coordinates = feature["geometry"]["coordinates"]
        line = [coordinates[index] for index in simplify_indices(coordinates)]
        key = properties["class"], properties["name"]
        groups.setdefault(key, []).append(line)
    for (road_class, name), lines in groups.items():
        compacted.append(
            {
                "type": "Feature",
                "properties": {"kind": "road", "class": road_class, "name": name},
                "geometry": {"type": "MultiLineString", "coordinates": lines},
            }
        )
    selected = [road for road in roads if road["class"] in ROUTE_CLASSES]
    occurrences = Counter(node for road in selected for node in set(road["nodes"]))
    graph = []
    for road in selected:
        pinned = [index for index, node in enumerate(road["nodes"]) if occurrences[node] > 1]
        indices = simplify_indices(road["coordinates"], pinned=pinned)
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


def convert(source, configuration, output, glyph_directory):
    import osmium

    manifest = json.loads(configuration.read_text(encoding="utf-8"))
    bounds = manifest["bounds"]
    glyph_ranges = {int(path.stem.split("-")[0]) for path in glyph_directory.glob("*.pbf")}
    features = []
    roads = []
    places = []

    class RegionReader(osmium.SimpleHandler):
        def node(self, node):
            if not node.tags:
                return
            tags = dict(node.tags)
            if tags.get("railway") not in {"station", "halt", "subway_entrance"} and tags.get(
                "place"
            ) not in {"suburb", "town", "neighbourhood"}:
                return
            point = [round(node.location.lon, 7), round(node.location.lat, 7)]
            name = map_name(tags, glyph_ranges)
            if name and inside(point, bounds):
                places.append(
                    {
                        "id": f"osm-node-{node.id}",
                        "name": name[:100],
                        "detail": "OSM station" if "railway" in tags else "OSM locality",
                        "point": point,
                    }
                )

        def way(self, way):
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
                features.append(feature)
            if road is not None:
                roads.append(road)

    with osmium.io.Reader(str(source)) as reader:
        timestamp = reader.header().get("osmosis_replication_timestamp")
    if not timestamp:
        raise ValueError("The OSM source must supply its data timestamp")
    RegionReader().apply_file(
        str(source),
        locations=True,
        idx="flex_mem",
        filters=[
            osmium.filter.KeyFilter("highway", "leisure", "natural", "waterway", "place", "railway")
        ],
    )
    seen_names = {place["name"].casefold() for place in manifest["places"]}
    for place in sorted(places, key=lambda item: (item["detail"], item["name"], item["id"])):
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
    features, roads = compact_region(features, roads)
    documents = {
        "manifest.json": manifest,
        "city.geojson": {"type": "FeatureCollection", "features": features},
        "roads.json": {"bounds": bounds, "roads": roads},
    }
    for name, document in documents.items():
        (output / name).write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    summary = {
        "source": source.name,
        "dataTimestamp": timestamp,
        "features": len(features),
        "sourceFeatures": raw_feature_count,
        "sourceDrivableWays": raw_road_count,
        "roadClasses": dict(road_classes),
        "geometryToleranceMeters": 1.0,
        "routingClasses": sorted(ROUTE_CLASSES),
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
    with source.open("rb") as source_file:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
        summary["sourceSha256"] = digest.hexdigest()
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
            ),
            indent=2,
        )
    )
    if arguments.pack:
        print(f"{build(arguments.output, arguments.pack)}  {arguments.pack}")


if __name__ == "__main__":
    main()
