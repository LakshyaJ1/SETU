from tools.build_map_tiles import minimum_zoom, tile_features


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
