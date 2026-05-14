"""GeoJSON FeatureCollection → RoadGraph 取り込み"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.preprocess.graph_model import InternalEdge, InternalNode, RoadGraph
from app.preprocess.helpers import _incident_edges_by_node, _node_degrees_from_incident
from app.preprocess.pipeline import GraphPreprocessOptions, preprocess_road_graph

from .projection import lon_lat_to_xy_m, xy_m_to_lon_lat

PILE_LONLAT_DECIMALS = 5


@dataclass
class WayPolyline:
    osm_way_id: int
    highway: str | None
    coords_lonlat: list[tuple[float, float]]
    osm_node_ids: list[int]


@dataclass
class GraphBuildResult:
    graph: RoadGraph
    lon0: float
    lat0: float
    explanation_lines: list[str]
    stats: dict[str, Any]
    step_metrics: dict[str, Any]


def parse_way_features(geojson_fc: dict[str, Any]) -> list[WayPolyline]:
    feats = geojson_fc.get("features") or []
    out: list[WayPolyline] = []
    if not isinstance(feats, list):
        return out
    for f in feats:
        if not isinstance(f, dict):
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        props = f.get("properties") or {}
        wid_raw = props.get("osm_way_id")
        if wid_raw is None:
            continue
        wid = int(wid_raw)
        hw = props.get("highway")
        highway = str(hw) if hw is not None else None
        ll: list[tuple[float, float]] = []
        for c in coords:
            if not isinstance(c, (list, tuple)) or len(c) < 2:
                continue
            ll.append((float(c[0]), float(c[1])))
        if len(ll) < 2:
            continue
        nids_raw = props.get("osm_node_ids")
        if not isinstance(nids_raw, list) or len(nids_raw) != len(ll):
            continue
        try:
            nids = [int(x) for x in nids_raw]
        except (TypeError, ValueError):
            continue
        out.append(WayPolyline(osm_way_id=wid, highway=highway, coords_lonlat=ll, osm_node_ids=nids))
    return out


def build_native_graph(
    ways: list[WayPolyline],
    project: Callable[[float, float], tuple[float, float]],
) -> RoadGraph:
    nodes: dict[str, InternalNode] = {}
    edges: dict[str, InternalEdge] = {}
    for w in ways:
        wid = w.osm_way_id
        ncoords = len(w.coords_lonlat)
        for i, (lon, lat) in enumerate(w.coords_lonlat):
            nid = f"native:{wid}:{i}"
            x_m, y_m = project(lon, lat)
            is_ep = i == 0 or i == ncoords - 1
            nodes[nid] = InternalNode(
                id=nid,
                x_m=x_m,
                y_m=y_m,
                source_osm_node_ids=[w.osm_node_ids[i]],
                is_way_polyline_endpoint=is_ep,
                merged_from_snap=False,
                merged_from_osm_id=False,
            )
        for i in range(ncoords - 1):
            u = f"native:{wid}:{i}"
            v = f"native:{wid}:{i + 1}"
            eid = f"e:{wid}:{i}"
            pu = (nodes[u].x_m, nodes[u].y_m)
            pv = (nodes[v].x_m, nodes[v].y_m)
            edges[eid] = InternalEdge(
                id=eid,
                u=u,
                v=v,
                polyline_xy_m=[pu, pv],
                osm_way_id=wid,
                highway=w.highway,
                merged_osm_way_ids=[wid],
            )
    return RoadGraph(nodes=nodes, edges=edges)


def classify_vertex_role(
    graph: RoadGraph,
    nid: str,
    deg: dict[str, int],
    incident: dict[str, list[InternalEdge]],
) -> Literal["inline", "junction"]:
    n = graph.nodes[nid]
    synthetic = len(n.source_osm_node_ids) == 0
    d = deg.get(nid, 0)
    if synthetic:
        return "junction"
    if d != 2:
        return "junction"
    if n.is_way_polyline_endpoint:
        return "junction"
    if len(n.source_osm_node_ids) > 1:
        return "junction"
    pair = incident.get(nid)
    if pair is None or len(pair) != 2:
        return "junction"
    e1, e2 = pair[0], pair[1]
    if e1.osm_way_id != e2.osm_way_id:
        return "junction"
    return "inline"


def graph_to_geojson_fc(
    graph: RoadGraph,
    lon0: float,
    lat0: float,
    options: GraphPreprocessOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    incident = _incident_edges_by_node(graph)
    deg = _node_degrees_from_incident(incident)

    roles: dict[str, str] = {}
    lonlat_by_nid: dict[str, tuple[float, float]] = {}
    for nid in graph.nodes:
        roles[nid] = classify_vertex_role(graph, nid, deg, incident)
        lon, lat = xy_m_to_lon_lat(lon0, lat0, graph.nodes[nid].x_m, graph.nodes[nid].y_m)
        lonlat_by_nid[nid] = (lon, lat)

    pile_key_counts: dict[tuple[float, float], int] = {}
    for lon, lat in lonlat_by_nid.values():
        key = (round(lon, PILE_LONLAT_DECIMALS), round(lat, PILE_LONLAT_DECIMALS))
        pile_key_counts[key] = pile_key_counts.get(key, 0) + 1

    node_feats: list[dict[str, Any]] = []
    for nid, n in graph.nodes.items():
        lon, lat = lonlat_by_nid[nid]
        pk = (round(lon, PILE_LONLAT_DECIMALS), round(lat, PILE_LONLAT_DECIMALS))
        pile_count = pile_key_counts.get(pk, 1)
        synthetic = len(n.source_osm_node_ids) == 0
        role = roles[nid]
        highlight_osm_merge = bool(options.connect_osm_node_ids_enabled and n.merged_from_osm_id)
        highlight_snap_merge = bool(options.snap_endpoints_enabled and n.merged_from_snap)

        node_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "internal_node_id": nid,
                    "source_osm_node_ids": n.source_osm_node_ids,
                    "synthetic": synthetic,
                    "graph_degree": deg.get(nid, 0),
                    "vertex_role": role,
                    "pile_count": pile_count,
                    "highlight_osm_merge": highlight_osm_merge,
                    "highlight_snap_merge": highlight_snap_merge,
                },
            }
        )

    edge_feats: list[dict[str, Any]] = []
    for eid, e in graph.edges.items():
        coords: list[list[float]] = []
        for p in e.polyline_xy_m:
            llon, llat = xy_m_to_lon_lat(lon0, lat0, p[0], p[1])
            coords.append([llon, llat])
        if len(coords) < 2:
            continue
        edge_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "internal_edge_id": eid,
                    "osm_way_id": e.osm_way_id,
                    "merged_osm_way_ids": e.merged_osm_way_ids,
                    "highway": e.highway,
                    "u": e.u,
                    "v": e.v,
                },
            }
        )

    nodes_fc: dict[str, Any] = {"type": "FeatureCollection", "features": node_feats}
    edges_fc: dict[str, Any] = {"type": "FeatureCollection", "features": edge_feats}
    return nodes_fc, edges_fc


def build_graph_from_geojson(
    geojson_fc: dict[str, Any],
    lon0: float,
    lat0: float,
    options: GraphPreprocessOptions,
) -> GraphBuildResult:
    ways = parse_way_features(geojson_fc)

    def proj(lon: float, lat: float) -> tuple[float, float]:
        return lon_lat_to_xy_m(lon0, lat0, lon, lat)

    graph = build_native_graph(ways, proj)
    step_metrics = preprocess_road_graph(graph, options)

    synth = sum(1 for n in graph.nodes.values() if len(n.source_osm_node_ids) == 0)
    stats = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "synthetic_node_count": synth,
        "way_input_count": len(ways),
    }

    return GraphBuildResult(
        graph=graph,
        lon0=lon0,
        lat0=lat0,
        explanation_lines=[],
        stats=stats,
        step_metrics=step_metrics,
    )
