"""
OSM way 折れ線から平面グラフへの変換パイプライン。

処理順（既定）:
1. ネイティブトポロジ（way 内の連続頂点間エッジ）
2. OSM node id による接続（オプション）
3. 距離ベース snap（オプション）
4. 重複・並行道路のマージ（オプション）
5. 道路交差の幾何 split（オプション）
6. 不要な中間ノード削除（オプション）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .defaults import (
    DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
    DEFAULT_ROAD_MERGE_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_DISTANCE_M,
    DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
)
from .helpers import _incident_edges_by_node, _node_degrees_from_incident
from ..graph_model import InternalEdge, InternalNode, RoadGraph
from ..projection import lon_lat_to_xy_m, xy_m_to_lon_lat

PILE_LONLAT_DECIMALS = 5


@dataclass
class GraphBuildOptions:
    connect_osm_node_ids: bool = True
    snap_endpoints: bool = False
    snap_epsilon_m: float = 3.0
    merge_duplicate_roads: bool = False
    road_merge_distance_m: float = DEFAULT_ROAD_MERGE_DISTANCE_M
    road_merge_angle_deg: float = DEFAULT_ROAD_MERGE_ANGLE_DEG
    road_merge_min_overlap_m: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_M
    road_merge_min_overlap_ratio: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO
    road_merge_anchor_delta_m: float = DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M
    road_merge_max_anchor_offset_m: float = DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M
    split_intersections: bool = False
    remove_redundant_chain_vertices: bool = True
    prune_chain_accum_angle_deg: float = DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG


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
    options: GraphBuildOptions,
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
        highlight_osm_merge = bool(options.connect_osm_node_ids and n.merged_from_osm_id)
        highlight_snap_merge = bool(options.snap_endpoints and n.merged_from_snap)

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


def apply_all_graph_build_options(graph: RoadGraph, options: GraphBuildOptions) -> dict[str, Any]:
    """5 つのオプションを既定順（connect_osm → snap → road_merge → split → prune）でグラフに適用し、step_metrics を返す。"""
    step_metrics: dict[str, Any] = {}
    if options.connect_osm_node_ids:
        from .connect_osm import merge_by_osm_node_id

        step_metrics["connect_osm"] = merge_by_osm_node_id(graph)
        step_metrics["connect_osm"]["merged_vertex_count"] = sum(
            1 for n in graph.nodes.values() if n.merged_from_osm_id
        )

    if options.snap_endpoints:
        from .snap_endpoints import snap_endpoints

        step_metrics["snap"] = snap_endpoints(graph, options.snap_epsilon_m)

    if options.merge_duplicate_roads:
        from .merge_duplicate_roads import merge_duplicate_roads

        step_metrics["road_merge"] = merge_duplicate_roads(
            graph,
            max_distance_m=options.road_merge_distance_m,
            max_angle_deg=options.road_merge_angle_deg,
            min_overlap_m=options.road_merge_min_overlap_m,
            min_overlap_ratio=options.road_merge_min_overlap_ratio,
            anchor_delta_m=options.road_merge_anchor_delta_m,
            max_anchor_offset_m=options.road_merge_max_anchor_offset_m,
        )

    if options.split_intersections:
        from .split_intersections import run_intersection_splits

        step_metrics["split"] = run_intersection_splits(graph)

    if options.remove_redundant_chain_vertices:
        from .prune_chains import prune_redundant_chain_vertices

        step_metrics["prune_chains"] = prune_redundant_chain_vertices(
            graph, options.prune_chain_accum_angle_deg
        )

    return step_metrics


def build_graph_from_geojson(
    geojson_fc: dict[str, Any],
    lon0: float,
    lat0: float,
    options: GraphBuildOptions,
) -> GraphBuildResult:
    ways = parse_way_features(geojson_fc)

    def proj(lon: float, lat: float) -> tuple[float, float]:
        return lon_lat_to_xy_m(lon0, lat0, lon, lat)

    graph = build_native_graph(ways, proj)
    step_metrics = apply_all_graph_build_options(graph, options)

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
