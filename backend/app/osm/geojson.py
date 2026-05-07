from typing import Any


def ways_to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        coords: list[list[float]] = []
        for node in geom:
            lat = node.get("lat")
            lon = node.get("lon")
            if lat is None or lon is None:
                continue
            coords.append([float(lon), float(lat)])
        if len(coords) < 2:
            continue
        tags = dict(el.get("tags") or {})
        way_id = el.get("id")
        # OSM に rare だが id=* タグがあると "id" がタグで上書きされ、一覧・強調のキーがずれる。
        # osm_way_id は必ずタグの後に置き、way の要素 id を固定する。
        properties = {**tags, "osm_way_id": way_id}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}
