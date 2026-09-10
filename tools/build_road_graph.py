"""Compile a SETU roads.json into a bounded, memory-mappable Android graph."""

import argparse
import gzip
import hashlib
import json
import math
import shutil
import struct
import sys
from array import array
from pathlib import Path

MAGIC = b"SETUGR1\n"
MAX_BYTES = 384 * 1024**2


def file_sha256(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate graph JSON field")
        result[key] = value
    return result


class JsonStream:
    def __init__(self, source):
        self.source = source
        self.buffer = ""
        self.position = 0
        self.decoder = json.JSONDecoder(object_pairs_hook=unique_object)

    def refill(self):
        chunk = self.source.read(65536)
        self.buffer = self.buffer[self.position :] + chunk
        self.position = 0
        if len(self.buffer) > 8 * 1024**2:
            raise ValueError("Oversized graph record")
        return bool(chunk)

    def peek(self):
        while True:
            while self.position < len(self.buffer) and self.buffer[self.position].isspace():
                self.position += 1
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if not self.refill():
                return ""

    def token(self, expected):
        if self.peek() != expected:
            raise ValueError(f"Expected graph JSON token {expected}")
        self.position += 1

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.position)
                if end == len(self.buffer):
                    if self.refill():
                        continue
                    self.position = len(self.buffer)
                    return value
                self.position = end
                return value
            except json.JSONDecodeError:
                if not self.refill():
                    raise ValueError("Incomplete graph JSON") from None


def integer(value):
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise ValueError("Road and node IDs must be int64 integers")
    return value


def distance(first, second):
    longitude, latitude = first
    other_longitude, other_latitude = second
    chord = (
        math.sin(math.radians(other_latitude - latitude) / 2) ** 2
        + math.cos(math.radians(latitude))
        * math.cos(math.radians(other_latitude))
        * math.sin(math.radians(other_longitude - longitude) / 2) ** 2
    )
    return 6_371_000 * 2 * math.atan2(math.sqrt(min(1, chord)), math.sqrt(max(0, 1 - chord)))


class GraphBuilder:
    def __init__(self, nodes=None, edges=None):
        if (nodes is None) != (edges is None):
            raise ValueError("Supply both indexed graph counts")
        if nodes is not None and (
            type(nodes) is not int
            or type(edges) is not int
            or not 1 <= nodes <= 4_000_000
            or not 1 <= edges <= 8_000_000
        ):
            raise ValueError("Invalid indexed graph counts")
        self.expected_nodes, self.expected_edges = nodes, edges
        self.latitudes = array("d", [math.nan]) * (nodes or 0)
        self.longitudes = array("d", [0]) * (nodes or 0)
        self.heads = array("i", [-1]) * (nodes or 0)
        self.sources, self.targets, self.next = array("i"), array("i"), array("i")
        self.lengths, self.name_ids = array("d"), array("i")
        self.node_indices, self.name_indices = {}, {}
        self.ways = set()
        self.references = 0

    def node(self, identifier, coordinates):
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise ValueError("Graph coordinates must be longitude/latitude pairs")
        longitude, latitude = coordinates
        if any(
            type(value) not in (int, float) or not math.isfinite(value) for value in coordinates
        ):
            raise ValueError("Invalid graph coordinate")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Invalid graph coordinate")
        integer(identifier)
        if self.expected_nodes is not None:
            if not 1 <= identifier <= self.expected_nodes:
                raise ValueError("Invalid indexed node ID")
            index = identifier - 1
        else:
            if identifier not in self.node_indices:
                self.node_indices[identifier] = len(self.latitudes)
                self.latitudes.append(math.nan)
                self.longitudes.append(0)
                self.heads.append(-1)
            index = self.node_indices[identifier]
        if index >= 4_000_000:
            raise ValueError("Too many graph nodes")
        if not math.isnan(self.latitudes[index]) and (
            self.latitudes[index] != latitude or self.longitudes[index] != longitude
        ):
            raise ValueError("A road node has conflicting coordinates")
        self.latitudes[index], self.longitudes[index] = latitude, longitude
        return index

    def road(self, road):
        if not isinstance(road, dict):
            raise ValueError("A road must be a JSON object")
        identifier = integer(road["id"])
        if identifier in self.ways or len(self.ways) >= 1_200_000:
            raise ValueError("Duplicate or excessive road IDs")
        self.ways.add(identifier)
        identifiers, coordinates = road["nodes"], road["coordinates"]
        if not isinstance(identifiers, list) or not 2 <= len(identifiers) <= 10000:
            raise ValueError("Invalid road node count")
        if not isinstance(coordinates, list) or len(coordinates) != len(identifiers):
            raise ValueError("Coordinate count mismatch")
        self.references += len(identifiers)
        if self.references > 6_000_000:
            raise ValueError("Too many graph node references")
        oneway = road.get("oneway", "no")
        if oneway not in ("no", "yes", "1", "true", "-1"):
            raise ValueError("Unsupported one-way value")
        name = road.get("name", "Local road")
        if not isinstance(name, str) or len(name.encode("utf-16-le")) > 400:
            raise ValueError("Invalid road name")
        name_id = self.name_indices.setdefault(name, len(self.name_indices))
        previous = self.node(identifiers[0], coordinates[0])
        for index in range(1, len(identifiers)):
            current = self.node(identifiers[index], coordinates[index])
            length = distance(coordinates[index - 1], coordinates[index])
            if oneway != "-1":
                self.edge(previous, current, length, name_id)
            if oneway in ("no", "-1"):
                self.edge(current, previous, length, name_id)
            previous = current

    def edge(self, source, target, length, name):
        index = len(self.sources)
        if index >= 8_000_000:
            raise ValueError("Too many graph edges")
        self.sources.append(source)
        self.targets.append(target)
        self.lengths.append(length)
        self.name_ids.append(name)
        self.next.append(self.heads[source])
        self.heads[source] = index

    def write(self, output):
        nodes, edges = len(self.latitudes), len(self.sources)
        if not nodes or not edges or any(math.isnan(value) for value in self.latitudes):
            raise ValueError("Graph is empty or has missing nodes")
        if self.expected_edges is not None and self.expected_edges != edges:
            raise ValueError("Graph edge count mismatch")
        with output.open("xb") as target:
            target.write(MAGIC + struct.pack("<iii", nodes, edges, len(self.name_indices)))
            for values in (
                self.latitudes,
                self.longitudes,
                self.heads,
                self.sources,
                self.targets,
                self.next,
                self.lengths,
                self.name_ids,
            ):
                if values.itemsize != (8 if values.typecode == "d" else 4):
                    raise ValueError("Unsupported native array width")
                if sys.byteorder != "little":
                    values.byteswap()
                values.tofile(target)
                if sys.byteorder != "little":
                    values.byteswap()
            for name in self.name_indices:
                encoded = name.encode("utf-8")
                target.write(struct.pack("<i", len(encoded)) + encoded)
            if target.tell() > MAX_BYTES:
                raise ValueError("Compiled graph exceeds the size limit")


def compile_graph(source: Path, destination: Path):
    if source.stat().st_size > 256 * 1024**2:
        raise ValueError("Source graph exceeds the size limit")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with source.open(encoding="utf-8") as original:
            stream = JsonStream(original)
            stream.token("{")
            fields, counts = set(), {}
            builder = None
            while stream.peek() != "}":
                if fields:
                    stream.token(",")
                field = stream.value()
                if not isinstance(field, str) or field in fields:
                    raise ValueError("Duplicate or invalid graph field")
                fields.add(field)
                stream.token(":")
                if field == "roads":
                    builder = GraphBuilder(counts.get("nodeCount"), counts.get("edgeCount"))
                    stream.token("[")
                    road_count = 0
                    while stream.peek() != "]":
                        if road_count:
                            stream.token(",")
                        builder.road(stream.value())
                        road_count += 1
                    stream.token("]")
                else:
                    value = stream.value()
                    if field in ("nodeCount", "edgeCount"):
                        if builder is not None:
                            raise ValueError("Graph counts must precede roads")
                        counts[field] = value
            stream.token("}")
            if stream.peek() or builder is None:
                raise ValueError("Missing graph or trailing JSON content")
        binary = destination / "roads.bin"
        builder.write(binary)
        checksum = file_sha256(binary)
        with (
            binary.open("rb") as content,
            (destination / "roads.bin.gzip").open("xb") as output,
            gzip.GzipFile(
                filename="", fileobj=output, mode="wb", mtime=0, compresslevel=6
            ) as compressed,
        ):
            shutil.copyfileobj(content, compressed)
        source_checksum = file_sha256(source)
        archive_checksum = file_sha256(destination / "roads.bin.gzip")
        metadata = {
            "schema": "setu.road-graph.v1",
            "archive": "roads.bin.gzip",
            "sha256": checksum,
            "sourceSha256": source_checksum,
            "bytes": binary.stat().st_size,
            "archiveBytes": (destination / "roads.bin.gzip").stat().st_size,
            "archiveSha256": archive_checksum,
            "nodes": len(builder.latitudes),
            "edges": len(builder.sources),
            "names": len(builder.name_indices),
        }
        (destination / "graph.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return metadata
    except BaseException:
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Validated roads.json source")
    parser.add_argument("destination", type=Path, help="New directory for graph artifacts")
    arguments = parser.parse_args()
    print(json.dumps(compile_graph(arguments.source, arguments.destination), indent=2))


if __name__ == "__main__":
    main()
