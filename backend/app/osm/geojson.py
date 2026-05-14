"""Overpass / OSM の JSON 要素列と GeoJSON FeatureCollection の相互変換。"""

from typing import Any


def ways_to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """`out geom` の way 要素のみから GeoJSON を生成（geometry に lat/lon のみある場合）。"""
    features: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        coords: list[list[float]] = []
        osm_node_ids: list[int] = []
        for node in geom:
            lat = node.get("lat")
            lon = node.get("lon")
            ref = node.get("ref")
            if lat is None or lon is None:
                continue
            coords.append([float(lon), float(lat)])
            if ref is not None:
                osm_node_ids.append(int(ref))
        if len(coords) < 2:
            continue
        tags = dict(el.get("tags") or {})
        way_id = el.get("id")
        properties = _way_properties(tags, way_id, osm_node_ids)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _way_properties(
    tags: dict[str, Any],
    way_id: Any,
    osm_node_ids: list[int],
) -> dict[str, Any]:
    ep_a = osm_node_ids[0] if osm_node_ids else None
    ep_b = osm_node_ids[-1] if len(osm_node_ids) >= 2 else None
    props = {
        **tags,
        "osm_way_id": way_id,
        "osm_node_ids": osm_node_ids,
        "osm_endpoint_node_a": ep_a,
        "osm_endpoint_node_b": ep_b,
    }
    return props


def overpass_elements_to_geojson(
    elements: list[dict[str, Any]],
    *,
    limit_ways: int | None = None,
) -> dict[str, Any]:
    """
    `out body` + `>;` + `out skel qt` で得た要素列から GeoJSON を構築する。
    way の `nodes` と node 要素の lat/lon で座標を復元する。
    """
    nodes_map: dict[int, tuple[float, float]] = {}
    ways_raw: list[dict[str, Any]] = []
    for el in elements:
        t = el.get("type")
        if t == "node":
            nid = el.get("id")
            lat, lon = el.get("lat"), el.get("lon")
            if nid is None or lat is None or lon is None:
                continue
            nodes_map[int(nid)] = (float(lat), float(lon))
        elif t == "way":
            ways_raw.append(el)

    ways_sorted = sorted(ways_raw, key=lambda w: int(w.get("id") or 0))
    if limit_ways is not None:
        ways_sorted = ways_sorted[:limit_ways]

    features: list[dict[str, Any]] = []
    for el in ways_sorted:
        node_refs = el.get("nodes")
        if not isinstance(node_refs, list) or len(node_refs) < 2:
            continue
        coords: list[list[float]] = []
        osm_node_ids: list[int] = []
        skip_way = False
        for ref in node_refs:
            nid = int(ref)
            ll = nodes_map.get(nid)
            if ll is None:
                skip_way = True
                break
            lat, lon = ll
            coords.append([lon, lat])
            osm_node_ids.append(nid)
        if skip_way or len(coords) < 2:
            continue
        tags = dict(el.get("tags") or {})
        way_id = el.get("id")
        properties = _way_properties(tags, way_id, osm_node_ids)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def slice_geojson_ways(
    geojson: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    """FeatureCollection の先頭 limit 件の way 相当フィーチャのみ残す。"""
    feats = geojson.get("features") or []
    if not isinstance(feats, list):
        return {"type": "FeatureCollection", "features": []}
    return {"type": "FeatureCollection", "features": feats[:limit]}
