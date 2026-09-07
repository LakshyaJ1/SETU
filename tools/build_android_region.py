"""Build the bundled Bengaluru demonstration map from public OpenStreetMap data."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "android/app/src/main/assets"
BBOX = (12.949, 77.575, 12.995, 77.625)
ENDPOINT = "https://overpass-api.de/api/interpreter"
DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "residential",
    "unclassified", "living_street", "service",
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bounds = ",".join(map(str, BBOX))
    query = (
        '[out:json][timeout:90];('
        f'way["highway"]({bounds});'
        f'way["leisure"~"park|garden"]({bounds});'
        f'way["natural"="water"]({bounds});'
        f'way["building"]({bounds});'
        ');out geom;'
    )
    request = urllib.request.Request(
        ENDPOINT, data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "SETU-Android-development/0.1 (offline map bundle)"},
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        source = json.load(response)
    features = []
    roads = []
    for element in source["elements"]:
        tags = element.get("tags", {})
        geometry = element.get("geometry", [])
        if len(geometry) < 2:
            continue
        coordinates = [[point["lon"], point["lat"]] for point in geometry]
        highway = tags.get("highway")
        kind = "road" if highway else (
            "park" if tags.get("leisure") in {"park", "garden"}
            else "water" if tags.get("natural") == "water" else "building"
        )
        polygon = kind != "road" and coordinates[0] == coordinates[-1]
        features.append({
            "type": "Feature",
            "properties": {
                "kind": kind, "class": highway or kind,
                "name": tags.get("name:en", tags.get("name", "")),
            },
            "geometry": {
                "type": "Polygon" if polygon else "LineString",
                "coordinates": [coordinates] if polygon else coordinates,
            },
        })
        if highway in DRIVABLE and tags.get("access") not in {"private", "no"}:
            roads.append({
                "id": element["id"], "nodes": element["nodes"],
                "coordinates": coordinates,
                "name": tags.get("name:en", tags.get("name", "Local road")),
                "oneway": tags.get("oneway", "yes" if tags.get("junction") == "roundabout" else "no"),
            })
    (OUTPUT / "bengaluru.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
        encoding="utf-8",
    )
    (OUTPUT / "bengaluru-roads.json").write_text(
        json.dumps({"bounds": BBOX, "roads": roads}, separators=(",", ":")), encoding="utf-8",
    )
    (OUTPUT / "map-attribution.json").write_text(json.dumps({
        "name": "Bengaluru Central", "source": "OpenStreetMap contributors",
        "license": "ODbL 1.0", "source_url": "https://www.openstreetmap.org/copyright",
        "bounds": BBOX, "timestamp": source.get("osm3s", {}).get("timestamp_osm_base"),
        "limitations": "Local development region. Routing does not yet apply turn-restriction relations.",
    }, indent=2), encoding="utf-8")
    glyph_ranges = {0}
    for feature in features:
        glyph_ranges.update(ord(character) // 256 * 256 for character in feature["properties"].get("name", ""))
    for start in sorted(glyph_ranges):
        glyph_range = f"{start}-{start + 255}"
        font_path = OUTPUT / f"fonts/Noto Sans Regular/{glyph_range}.pbf"
        font_path.parent.mkdir(parents=True, exist_ok=True)
        font_url = f"https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular/{glyph_range}.pbf"
        with urllib.request.urlopen(font_url, timeout=30) as response:
            font_path.write_bytes(response.read())
    print(f"Built {len(features)} map features and {len(roads)} routable ways.")


if __name__ == "__main__":
    main()
