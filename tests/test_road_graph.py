import gzip
import hashlib
import io
import json
import struct
from pathlib import Path

import pytest

from tools.build_road_graph import JsonStream, compile_graph, distance

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "android/app/src/androidTest/assets/map-fixture/roads.json"
)


def test_compilation_is_deterministic_and_preserves_topology_and_si_lengths(tmp_path):
    metadata = compile_graph(FIXTURE, tmp_path / "first")
    second = compile_graph(FIXTURE, tmp_path / "second")
    assert metadata == second
    data = (tmp_path / "first/roads.bin").read_bytes()
    assert gzip.decompress((tmp_path / "first/roads.bin.gzip").read_bytes()) == data
    assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    assert metadata["sourceSha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert data[:8] == b"SETUGR1\n"
    nodes, edges, name_count = struct.unpack_from("<iii", data, 8)
    position = 20

    def values(code, count):
        nonlocal position
        result = struct.unpack_from(f"<{count}{code}", data, position)
        position += struct.calcsize(code) * count
        return result

    latitudes, longitudes = values("d", nodes), values("d", nodes)
    heads = values("i", nodes)
    sources, targets, links = values("i", edges), values("i", edges), values("i", edges)
    lengths, name_ids = values("d", edges), values("i", edges)
    names = []
    for _ in range(name_count):
        length = values("i", 1)[0]
        names.append(data[position : position + length].decode("utf-8"))
        position += length
    assert position == len(data)
    roads = json.loads(FIXTURE.read_text())["roads"]
    assert edges == sum(
        (len(road["nodes"]) - 1) * (2 if road["oneway"] == "no" else 1) for road in roads
    )
    linked = set()
    for node, head in enumerate(heads):
        while head != -1:
            assert sources[head] == node and head not in linked
            linked.add(head)
            target = targets[head]
            assert lengths[head] == pytest.approx(
                distance(
                    (longitudes[node], latitudes[node]), (longitudes[target], latitudes[target])
                )
            )
            assert names[name_ids[head]] in {road["name"] for road in roads}
            assert links[head] < head
            head = links[head]
    assert len(linked) == edges
    with pytest.raises(FileExistsError):
        compile_graph(FIXTURE, tmp_path / "first")
    assert (tmp_path / "first/roads.bin").read_bytes() == data


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_field",
        "duplicate_way",
        "fractional_node",
        "conflict",
        "bad_oneway",
        "trailing",
        "late_count",
        "count_mismatch",
        "missing_node",
        "bad_name",
        "nan_coordinate",
    ],
)
def test_malformed_graphs_are_rejected_without_partial_artifacts(tmp_path, mutation):
    document = {
        "roads": [
            {
                "id": 1,
                "nodes": [1, 2],
                "coordinates": [[77.0, 28.0], [77.1, 28.0]],
                "oneway": "no",
                "name": "Road",
            }
        ]
    }
    road = document["roads"][0]
    if mutation == "duplicate_way":
        document["roads"].append(road.copy())
    elif mutation == "fractional_node":
        road["nodes"][0] = 1.5
    elif mutation == "conflict":
        road["nodes"] = [1, 1]
    elif mutation == "bad_oneway":
        road["oneway"] = "sometimes"
    elif mutation == "late_count":
        document["nodeCount"] = 2
    elif mutation == "count_mismatch":
        document = {"nodeCount": 2, "edgeCount": 3, **document}
    elif mutation == "missing_node":
        document = {"nodeCount": 3, "edgeCount": 2, **document}
    elif mutation == "bad_name":
        road["name"] = "a" * 201
    elif mutation == "nan_coordinate":
        road["coordinates"][0][0] = float("nan")
    text = json.dumps(document)
    if mutation == "duplicate_field":
        text = text.replace('"id": 1', '"id": 1, "id": 2')
    if mutation == "trailing":
        text += "{}"
    source = tmp_path / "roads.json"
    source.write_text(text)
    with pytest.raises(ValueError):
        compile_graph(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_stream_parser_handles_small_chunks_unicode_and_eof_without_losing_positions():
    class SmallReader(io.StringIO):
        def read(self, size=-1):
            return super().read(min(size, 3))

    stream = JsonStream(SmallReader('{"name":"मार्ग", "count":12345}'))
    stream.token("{")
    assert stream.value() == "name"
    stream.token(":")
    assert stream.value() == "मार्ग"
    stream.token(",")
    assert stream.value() == "count"
    stream.token(":")
    assert stream.value() == 12345
    stream.token("}")
    assert stream.peek() == ""
    eof = JsonStream(SmallReader("12345"))
    assert eof.value() == 12345
    assert eof.peek() == ""
