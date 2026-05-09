"""
OSM way 折れ線から平面グラフへの変換パイプライン。

処理順（既定）:
1. ネイティブトポロジ（way 内の連続頂点間エッジ）
2. OSM node id による接続（オプション）
3. 距離ベース snap（オプション）
4. 重複・並行道路のマージ（オプション）
5. 道路交差の幾何 split（オプション）
6. 不要な中間ノード削除（オプション・上記の後のみ）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from .graph_model import InternalEdge, InternalNode, RoadGraph
from .projection import lon_lat_to_xy_m, xy_m_to_lon_lat


DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG = 15.0
DEFAULT_ROAD_MERGE_DISTANCE_M = 14.0
DEFAULT_ROAD_MERGE_ANGLE_DEG = 22.0
DEFAULT_ROAD_MERGE_MIN_OVERLAP_M = 8.0
DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO = 0.25
DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M = 2.0


@dataclass
class GraphBuildOptions:
    connect_osm_node_ids: bool = False
    snap_endpoints: bool = False
    snap_epsilon_m: float = 3.0
    merge_duplicate_roads: bool = False
    road_merge_distance_m: float = DEFAULT_ROAD_MERGE_DISTANCE_M
    road_merge_angle_deg: float = DEFAULT_ROAD_MERGE_ANGLE_DEG
    road_merge_min_overlap_m: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_M
    road_merge_min_overlap_ratio: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO
    road_merge_anchor_delta_m: float = DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M
    split_intersections: bool = False
    remove_redundant_chain_vertices: bool = False
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


# --- geometry primitives (meters) ---
SEG_PT_TOL_M = 0.05
PARALLEL_EPS = 1e-12
MAX_SPLIT_ITER = 2000

PILE_LONLAT_DECIMALS = 5

_PRUNE_LEN_EPS_SQ = 1e-18


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def segment_intersection_interior(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """両セグメントの真の内部で交わる唯一の点を返す（端は除外）。"""
    eps_t = 1e-9
    r = _sub(b, a)
    s = _sub(d, c)
    denom = _cross(r[0], r[1], s[0], s[1])
    if abs(denom) < PARALLEL_EPS:
        return None
    qp = _sub(c, a)
    t = _cross(qp[0], qp[1], s[0], s[1]) / denom
    u = _cross(qp[0], qp[1], r[0], r[1]) / denom
    if t <= eps_t or t >= 1.0 - eps_t:
        return None
    if u <= eps_t or u >= 1.0 - eps_t:
        return None
    return (a[0] + t * r[0], a[1] + t * r[1])


def nearest_point_on_segment(
    q: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    vx, vy = _sub(b, a)
    len2 = vx * vx + vy * vy
    if len2 < 1e-18:
        return a, 0.0
    t = ((_sub(q, a)[0]) * vx + (_sub(q, a)[1]) * vy) / len2
    t = max(0.0, min(1.0, t))
    return (a[0] + t * vx, a[1] + t * vy), t


# --- GeoJSON parsing ---


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


def _merge_source_ids(lists: list[list[int]]) -> list[int]:
    s: set[int] = set()
    for lst in lists:
        for x in lst:
            s.add(x)
    return sorted(s)


def merge_by_osm_node_id(graph: RoadGraph) -> dict[str, Any]:
    """
    同一 OSM node id を共有するグラフ頂点を union-find でまとめ、一括で remap する。
    osm_id_groups_merged は「重複があった OSM id」の数（初期グラフ上）。
    """
    groups: dict[int, list[str]] = {}
    for nid, node in graph.nodes.items():
        for osm_id in node.source_osm_node_ids:
            groups.setdefault(osm_id, []).append(nid)
    osm_id_groups_merged = sum(1 for _oid, members in groups.items() if len(set(members)) >= 2)

    parent = {n: n for n in graph.nodes}
    for _oid, members in groups.items():
        uniq = sorted(set(members))
        if len(uniq) < 2:
            continue
        base = uniq[0]
        for other in uniq[1:]:
            _uf_union(parent, base, other)

    clusters: dict[str, list[str]] = {}
    for nid in graph.nodes:
        r = _uf_find(parent, nid)
        clusters.setdefault(r, []).append(nid)

    rem: dict[str, str] = {}
    merged_canonical: dict[str, InternalNode] = {}
    vertices_removed = 0
    for _root, members in clusters.items():
        canonical = min(members)
        for k in members:
            rem[k] = canonical
        if len(members) < 2:
            continue
        vertices_removed += len(members) - 1
        xs = sum(graph.nodes[k].x_m for k in members) / len(members)
        ys = sum(graph.nodes[k].y_m for k in members) / len(members)
        src = _merge_source_ids([graph.nodes[k].source_osm_node_ids for k in members])
        ep_any = any(graph.nodes[k].is_way_polyline_endpoint for k in members)
        snap_any = any(graph.nodes[k].merged_from_snap for k in members)
        road_merge_any = any(graph.nodes[k].merged_from_road_merge for k in members)
        osm_merge_any = True
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=snap_any,
            merged_from_osm_id=osm_merge_any,
            merged_from_road_merge=road_merge_any,
            synthetic_reason=None,
        )

    final_nodes: dict[str, InternalNode] = {}
    for nid, node in graph.nodes.items():
        if rem[nid] != nid:
            continue
        if nid in merged_canonical:
            final_nodes[nid] = merged_canonical[nid]
        else:
            final_nodes[nid] = InternalNode(
                id=nid,
                x_m=node.x_m,
                y_m=node.y_m,
                source_osm_node_ids=list(node.source_osm_node_ids),
                is_way_polyline_endpoint=node.is_way_polyline_endpoint,
                merged_from_snap=node.merged_from_snap,
                merged_from_osm_id=node.merged_from_osm_id,
                merged_from_road_merge=node.merged_from_road_merge,
                synthetic_reason=node.synthetic_reason,
            )

    new_edges: dict[str, InternalEdge] = {}
    for eid, e in graph.edges.items():
        u = rem[e.u]
        v = rem[e.v]
        if u == v:
            continue
        pl = list(e.polyline_xy_m)
        if pl:
            nu = final_nodes[u]
            nv = final_nodes[v]
            pl[0] = (nu.x_m, nu.y_m)
            pl[-1] = (nv.x_m, nv.y_m)
        new_edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=pl,
            osm_way_id=e.osm_way_id,
            highway=e.highway,
            merged_osm_way_ids=list(e.merged_osm_way_ids),
        )
    graph.nodes = final_nodes
    graph.edges = new_edges
    return {
        "osm_id_groups_merged": osm_id_groups_merged,
        "graph_vertices_removed_by_merge": vertices_removed,
    }


def _uf_find(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _uf_union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra != rb:
        parent[rb] = ra


def snap_endpoints(graph: RoadGraph, epsilon_m: float) -> dict[str, Any]:
    """ε 近傍の頂点を union（条件付き）。

    - 同一グラフ辺の両端どうしは結合しない（polyline 上の隣接頂点同士を除外）。
    - どちらも OSM 折れ線の端点でない頂点同士は結合しない。
    """
    eps = max(epsilon_m, 1e-6)
    nids = list(graph.nodes.keys())
    pts = [Point(graph.nodes[i].x_m, graph.nodes[i].y_m) for i in nids]
    tree = STRtree(pts)

    direct_edge_pairs: set[tuple[str, str]] = set()
    for e in graph.edges.values():
        a, b = e.u, e.v
        if a > b:
            a, b = b, a
        direct_edge_pairs.add((a, b))

    parent = {n: n for n in graph.nodes}
    for nid in nids:
        na = graph.nodes[nid]
        q = Point(na.x_m, na.y_m)
        hits = tree.query(q, predicate="dwithin", distance=eps)
        for hj in np.atleast_1d(np.asarray(hits)):
            j = int(hj)
            oid = nids[j]
            if oid <= nid:
                continue
            nb = graph.nodes[oid]
            pu = (nid, oid) if nid < oid else (oid, nid)
            if pu in direct_edge_pairs:
                continue
            if not (na.is_way_polyline_endpoint or nb.is_way_polyline_endpoint):
                continue
            if _dist((na.x_m, na.y_m), (nb.x_m, nb.y_m)) <= epsilon_m:
                _uf_union(parent, nid, oid)

    clusters: dict[str, list[str]] = {}
    for n in graph.nodes:
        r = _uf_find(parent, n)
        clusters.setdefault(r, []).append(n)

    rem: dict[str, str] = {}
    merged_canonical: dict[str, InternalNode] = {}
    snap_clusters = 0
    vertices_merged = 0
    for _root, members in clusters.items():
        canonical = min(members)
        for k in members:
            rem[k] = canonical
        if len(members) < 2:
            continue
        snap_clusters += 1
        vertices_merged += len(members) - 1
        xs = sum(graph.nodes[k].x_m for k in members) / len(members)
        ys = sum(graph.nodes[k].y_m for k in members) / len(members)
        src = _merge_source_ids([graph.nodes[k].source_osm_node_ids for k in members])
        ep_any = any(graph.nodes[k].is_way_polyline_endpoint for k in members)
        osm_merge_any = any(graph.nodes[k].merged_from_osm_id for k in members)
        road_merge_any = any(graph.nodes[k].merged_from_road_merge for k in members)
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=True,
            merged_from_osm_id=osm_merge_any,
            merged_from_road_merge=road_merge_any,
            synthetic_reason=None,
        )

    final_nodes: dict[str, InternalNode] = {}
    for nid, node in graph.nodes.items():
        if rem[nid] != nid:
            continue
        if nid in merged_canonical:
            final_nodes[nid] = merged_canonical[nid]
        else:
            final_nodes[nid] = InternalNode(
                id=nid,
                x_m=node.x_m,
                y_m=node.y_m,
                source_osm_node_ids=list(node.source_osm_node_ids),
                is_way_polyline_endpoint=node.is_way_polyline_endpoint,
                merged_from_snap=node.merged_from_snap,
                merged_from_osm_id=node.merged_from_osm_id,
                merged_from_road_merge=node.merged_from_road_merge,
                synthetic_reason=node.synthetic_reason,
            )

    new_edges: dict[str, InternalEdge] = {}
    for eid, e in graph.edges.items():
        u = rem[e.u]
        v = rem[e.v]
        if u == v:
            continue
        pl = list(e.polyline_xy_m)
        if pl:
            nu = final_nodes[u]
            nv = final_nodes[v]
            pl[0] = (nu.x_m, nu.y_m)
            pl[-1] = (nv.x_m, nv.y_m)
        new_edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=pl,
            osm_way_id=e.osm_way_id,
            highway=e.highway,
            merged_osm_way_ids=list(e.merged_osm_way_ids),
        )
    graph.nodes = final_nodes
    graph.edges = new_edges
    return {
        "epsilon_m": epsilon_m,
        "snap_clusters": snap_clusters,
        "vertices_merged_by_snap": vertices_merged,
    }


@dataclass
class _RoadMergeCandidate:
    a: str
    b: str
    score: float
    distance_m: float
    angle_deg: float
    overlap_m: float
    len_a_m: float
    len_b_m: float


@dataclass
class _DirectedRoadMerge:
    source: str
    target: str
    score: float


def _edge_way_ids(e: InternalEdge) -> list[int]:
    ids = list(e.merged_osm_way_ids)
    if e.osm_way_id is not None:
        ids.append(e.osm_way_id)
    return sorted(set(ids))


def _merge_edge_osm_way_ids(edges: list[InternalEdge]) -> list[int]:
    out: set[int] = set()
    for e in edges:
        out.update(_edge_way_ids(e))
    return sorted(out)


def _edge_endpoints_xy(graph: RoadGraph, e: InternalEdge) -> tuple[tuple[float, float], tuple[float, float]]:
    nu = graph.nodes[e.u]
    nv = graph.nodes[e.v]
    return (nu.x_m, nu.y_m), (nv.x_m, nv.y_m)


def _edge_length_m(graph: RoadGraph, e: InternalEdge) -> float:
    a, b = _edge_endpoints_xy(graph, e)
    return _dist(a, b)


def _parallel_overlap_m(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> float:
    ax, ay = a1[0] - a0[0], a1[1] - a0[1]
    la = math.hypot(ax, ay)
    if la < 1e-9:
        return 0.0
    ux, uy = ax / la, ay / la
    p0 = (b0[0] - a0[0]) * ux + (b0[1] - a0[1]) * uy
    p1 = (b1[0] - a0[0]) * ux + (b1[1] - a0[1]) * uy
    lo, hi = sorted((p0, p1))
    return max(0.0, min(la, hi) - max(0.0, lo))


def _point_segment_distance(
    q: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    p, _t = nearest_point_on_segment(q, a, b)
    return _dist(q, p)


def _road_merge_relaxed_angle_limit_deg(
    base_angle_deg: float,
    distance_m: float,
    max_distance_m: float,
    overlap_m: float,
    required_overlap_m: float,
    endpoint_near_m: float,
) -> float:
    """近くで十分重なる候補は、端点付近で発散していても少し広めに見る。"""
    limit = base_angle_deg
    if distance_m <= max_distance_m and overlap_m >= required_overlap_m:
        limit = max(limit, base_angle_deg + 10.0)
    if endpoint_near_m <= max_distance_m * 1.25 and overlap_m >= required_overlap_m * 0.75:
        limit = max(limit, base_angle_deg + 18.0)
    return min(limit, 45.0)


def _road_merge_pair_metric(
    graph: RoadGraph,
    e1: InternalEdge,
    e2: InternalEdge,
    max_distance_m: float,
    max_angle_deg: float,
    min_overlap_m: float,
    min_overlap_ratio: float,
) -> _RoadMergeCandidate | None:
    if e1.osm_way_id is not None and e1.osm_way_id == e2.osm_way_id:
        return None
    a0, a1 = _edge_endpoints_xy(graph, e1)
    b0, b1 = _edge_endpoints_xy(graph, e2)
    ax, ay = a1[0] - a0[0], a1[1] - a0[1]
    bx, by = b1[0] - b0[0], b1[1] - b0[1]
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la < 1e-6 or lb < 1e-6:
        return None
    distance_m = LineString([a0, a1]).distance(LineString([b0, b1]))
    if distance_m > max_distance_m:
        return None
    overlap_ab = _parallel_overlap_m(a0, a1, b0, b1)
    overlap_ba = _parallel_overlap_m(b0, b1, a0, a1)
    overlap_m = min(overlap_ab, overlap_ba)
    required_overlap = max(min_overlap_m, min_overlap_ratio * min(la, lb))
    if overlap_m < required_overlap:
        return None
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    angle = abs(math.atan2(cross, dot))
    angle = min(angle, math.pi - angle)
    angle_deg = math.degrees(angle)
    endpoint_near_m = min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )
    angle_limit = _road_merge_relaxed_angle_limit_deg(
        max_angle_deg, distance_m, max_distance_m, overlap_m, required_overlap, endpoint_near_m
    )
    if angle_deg > angle_limit:
        return None
    score = overlap_m - distance_m * 3.0 - angle_deg * 0.5
    return _RoadMergeCandidate(
        a=e1.id,
        b=e2.id,
        score=score,
        distance_m=distance_m,
        angle_deg=angle_deg,
        overlap_m=overlap_m,
        len_a_m=la,
        len_b_m=lb,
    )


def _road_merge_candidates(
    graph: RoadGraph,
    max_distance_m: float,
    max_angle_deg: float,
    min_overlap_m: float,
    min_overlap_ratio: float,
) -> list[_RoadMergeCandidate]:
    edge_ids = sorted(graph.edges)
    geoms: list[LineString] = []
    refs: list[str] = []
    for eid in edge_ids:
        e = graph.edges[eid]
        a, b = _edge_endpoints_xy(graph, e)
        if _dist(a, b) < 1e-6:
            continue
        geoms.append(LineString([a, b]))
        refs.append(eid)
    if len(geoms) < 2:
        return []
    tree = STRtree(geoms)
    raw = tree.query(np.asarray(geoms, dtype=object), predicate="dwithin", distance=max_distance_m)
    seen: set[tuple[str, str]] = set()
    out: list[_RoadMergeCandidate] = []
    if raw.ndim == 2 and raw.shape[0] == 2:
        for k in range(raw.shape[1]):
            i, j = int(raw[0, k]), int(raw[1, k])
            if i >= j:
                continue
            e1_id, e2_id = refs[i], refs[j]
            key = (e1_id, e2_id) if e1_id < e2_id else (e2_id, e1_id)
            if key in seen:
                continue
            seen.add(key)
            e1 = graph.edges.get(e1_id)
            e2 = graph.edges.get(e2_id)
            if e1 is None or e2 is None:
                continue
            metric = _road_merge_pair_metric(
                graph, e1, e2, max_distance_m, max_angle_deg, min_overlap_m, min_overlap_ratio
            )
            if metric is not None:
                out.append(metric)
    out.sort(key=lambda c: (-c.score, c.a, c.b))
    return out


def _initial_directed_road_merges(
    graph: RoadGraph,
    candidates: list[_RoadMergeCandidate],
) -> list[_DirectedRoadMerge]:
    pair_counts: dict[str, int] = {}
    for c in candidates:
        pair_counts[c.a] = pair_counts.get(c.a, 0) + 1
        pair_counts[c.b] = pair_counts.get(c.b, 0) + 1

    directed: list[_DirectedRoadMerge] = []
    for c in candidates:
        ca, cb = pair_counts.get(c.a, 0), pair_counts.get(c.b, 0)
        a_is_hub = ca >= 3
        b_is_hub = cb >= 3
        if a_is_hub and not b_is_hub:
            source, target = c.b, c.a
        elif b_is_hub and not a_is_hub:
            source, target = c.a, c.b
        elif c.len_a_m > c.len_b_m:
            source, target = c.b, c.a
        elif c.len_b_m > c.len_a_m:
            source, target = c.a, c.b
        else:
            # Stable tie-break: keep lexicographically smaller edge as representative.
            source, target = (c.b, c.a) if c.a < c.b else (c.a, c.b)
        directed.append(_DirectedRoadMerge(source=source, target=target, score=c.score))
    directed.sort(key=lambda e: (e.source, -e.score, e.target))
    return directed


def _road_merge_outdegree(edges: list[_DirectedRoadMerge]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in edges:
        out[e.source] = out.get(e.source, 0) + 1
        out.setdefault(e.target, out.get(e.target, 0))
    return out


def _repair_road_merge_directions(edges: list[_DirectedRoadMerge]) -> tuple[list[_DirectedRoadMerge], int]:
    current = list(edges)
    repaired = 0
    changed = True
    while changed:
        changed = False
        out = _road_merge_outdegree(current)
        offenders = {src for src, deg in out.items() if deg >= 2}
        reverse_keys = {
            (e.source, e.target)
            for e in current
            if e.source in offenders and out.get(e.target, 0) == 0
        }
        if not reverse_keys:
            break
        next_edges: list[_DirectedRoadMerge] = []
        for e in sorted(current, key=lambda x: (x.source, -x.score, x.target)):
            if (e.source, e.target) in reverse_keys:
                next_edges.append(_DirectedRoadMerge(source=e.target, target=e.source, score=e.score))
                repaired += 1
                changed = True
            else:
                next_edges.append(e)
        current = next_edges
    current.sort(key=lambda e: (e.source, -e.score, e.target))
    return current, repaired


def _prune_road_merge_outdegree(edges: list[_DirectedRoadMerge]) -> tuple[list[_DirectedRoadMerge], int]:
    by_source: dict[str, list[_DirectedRoadMerge]] = {}
    for e in edges:
        by_source.setdefault(e.source, []).append(e)
    kept: list[_DirectedRoadMerge] = []
    removed = 0
    for src in sorted(by_source):
        choices = sorted(by_source[src], key=lambda e: (-e.score, e.target))
        kept.append(choices[0])
        removed += max(0, len(choices) - 1)
    kept.sort(key=lambda e: (e.source, e.target))
    return kept, removed


def _road_merge_topological_order(edges: list[_DirectedRoadMerge]) -> list[str] | None:
    nodes: set[str] = set()
    outgoing: dict[str, list[str]] = {}
    indeg: dict[str, int] = {}
    for e in edges:
        nodes.add(e.source)
        nodes.add(e.target)
        outgoing.setdefault(e.source, []).append(e.target)
        indeg[e.target] = indeg.get(e.target, 0) + 1
        indeg.setdefault(e.source, indeg.get(e.source, 0))
    ready = sorted(n for n in nodes if indeg.get(n, 0) == 0)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(outgoing.get(n, [])):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    if len(order) != len(nodes):
        return None
    return order


def _break_road_merge_cycles(edges: list[_DirectedRoadMerge]) -> tuple[list[_DirectedRoadMerge], int]:
    current = list(edges)
    removed = 0
    while _road_merge_topological_order(current) is None and current:
        nodes_in_cycles = {e.source for e in current} | {e.target for e in current}
        candidates = [e for e in current if e.source in nodes_in_cycles and e.target in nodes_in_cycles]
        drop = min(candidates or current, key=lambda e: (e.score, e.source, e.target))
        current.remove(drop)
        removed += 1
    current.sort(key=lambda e: (e.source, e.target))
    return current, removed


def _resolve_road_merge_target(src: str, out: dict[str, str]) -> str:
    seen: set[str] = set()
    cur = src
    while cur in out and cur not in seen:
        seen.add(cur)
        cur = out[cur]
    return cur


def _nearest_point_on_polyline(
    q: tuple[float, float],
    poly: list[tuple[float, float]],
) -> tuple[tuple[float, float], float, float]:
    best_pt = poly[0]
    best_d = 1e18
    best_m = 0.0
    acc = 0.0
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        proj, t = nearest_point_on_segment(q, a, b)
        d = _dist(q, proj)
        seg_len = _dist(a, b)
        if d < best_d:
            best_pt = proj
            best_d = d
            best_m = acc + t * seg_len
        acc += seg_len
    return best_pt, best_d, best_m


def _road_merge_anchor_for_node(
    graph: RoadGraph,
    target_edge: InternalEdge,
    source_nid: str,
    anchors: list[tuple[float, str]],
    anchor_delta_m: float,
    synth_counter: list[int],
) -> tuple[str, bool]:
    source_node = graph.nodes[source_nid]
    q = (source_node.x_m, source_node.y_m)
    h, _dist_to_line, measure = _nearest_point_on_polyline(q, target_edge.polyline_xy_m)

    for _m, nid in anchors:
        n = graph.nodes[nid]
        if _dist(h, (n.x_m, n.y_m)) <= anchor_delta_m:
            return nid, False

    synth_counter[0] += 1
    nid = f"roadmerge:{synth_counter[0]}"
    while nid in graph.nodes:
        synth_counter[0] += 1
        nid = f"roadmerge:{synth_counter[0]}"
    graph.nodes[nid] = InternalNode(
        id=nid,
        x_m=h[0],
        y_m=h[1],
        source_osm_node_ids=[],
        is_way_polyline_endpoint=False,
        merged_from_snap=False,
        merged_from_osm_id=False,
        merged_from_road_merge=True,
        synthetic_reason="road_merge",
    )
    anchors.append((measure, nid))
    return nid, True


def _resnap_edge_endpoint_polylines(graph: RoadGraph, e: InternalEdge) -> None:
    if not e.polyline_xy_m or e.u not in graph.nodes or e.v not in graph.nodes:
        return
    nu = graph.nodes[e.u]
    nv = graph.nodes[e.v]
    pl = list(e.polyline_xy_m)
    pl[0] = (nu.x_m, nu.y_m)
    pl[-1] = (nv.x_m, nv.y_m)
    e.polyline_xy_m = pl


def _apply_road_merge_batch(
    graph: RoadGraph,
    target_id: str,
    source_ids: list[str],
    anchor_delta_m: float,
    batch_index: int,
    synth_counter: list[int],
) -> tuple[int, int, int]:
    target = graph.edges.get(target_id)
    if target is None:
        return (0, 0, 0)
    sources = [graph.edges[s] for s in source_ids if s in graph.edges and s != target_id]
    if not sources:
        return (0, 0, 0)

    target_len = sum(_dist(target.polyline_xy_m[i], target.polyline_xy_m[i + 1]) for i in range(len(target.polyline_xy_m) - 1))
    anchors: list[tuple[float, str]] = [(0.0, target.u), (target_len, target.v)]
    source_edge_ids = {e.id for e in sources}
    source_node_ids: set[str] = set()
    anchor_for_source_node: dict[str, str] = {}
    anchors_created = 0
    for src in sources:
        source_node_ids.add(src.u)
        source_node_ids.add(src.v)
        for nid in (src.u, src.v):
            anchor, created = _road_merge_anchor_for_node(
                graph, target, nid, anchors, anchor_delta_m, synth_counter
            )
            anchor_for_source_node[nid] = anchor
            if created:
                anchors_created += 1

    incident_remapped = 0
    delete_edges = set(source_edge_ids)
    for eid, e in list(graph.edges.items()):
        if eid in delete_edges or eid == target_id:
            continue
        changed = False
        if e.u in anchor_for_source_node:
            e.u = anchor_for_source_node[e.u]
            changed = True
        if e.v in anchor_for_source_node:
            e.v = anchor_for_source_node[e.v]
            changed = True
        if changed:
            if e.u == e.v:
                delete_edges.add(eid)
            else:
                _resnap_edge_endpoint_polylines(graph, e)
                incident_remapped += 1

    provenance = _merge_edge_osm_way_ids([target] + sources)
    for eid in delete_edges:
        graph.edges.pop(eid, None)
    graph.edges.pop(target_id, None)

    anchors_sorted: list[tuple[float, str]] = []
    seen_anchor_ids: set[str] = set()
    for measure, nid in sorted(anchors, key=lambda x: (x[0], x[1])):
        if nid in seen_anchor_ids:
            continue
        if nid not in graph.nodes:
            continue
        seen_anchor_ids.add(nid)
        anchors_sorted.append((measure, nid))

    for i in range(len(anchors_sorted) - 1):
        u = anchors_sorted[i][1]
        v = anchors_sorted[i + 1][1]
        if u == v:
            continue
        nu = graph.nodes[u]
        nv = graph.nodes[v]
        eid = f"roadmerge:{batch_index}:{i}:{target_id}"
        graph.edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=[(nu.x_m, nu.y_m), (nv.x_m, nv.y_m)],
            osm_way_id=target.osm_way_id,
            highway=target.highway,
            merged_osm_way_ids=provenance,
        )

    inc = _incident_edges_by_node(graph)
    for nid in source_node_ids:
        if nid in graph.nodes and not inc.get(nid):
            del graph.nodes[nid]
    return (len(sources), anchors_created, incident_remapped)


def merge_duplicate_roads(
    graph: RoadGraph,
    max_distance_m: float = DEFAULT_ROAD_MERGE_DISTANCE_M,
    max_angle_deg: float = DEFAULT_ROAD_MERGE_ANGLE_DEG,
    min_overlap_m: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    min_overlap_ratio: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
    anchor_delta_m: float = DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
) -> dict[str, Any]:
    candidates = _road_merge_candidates(
        graph,
        max_distance_m=max_distance_m,
        max_angle_deg=max_angle_deg,
        min_overlap_m=min_overlap_m,
        min_overlap_ratio=min_overlap_ratio,
    )
    directed = _initial_directed_road_merges(graph, candidates)
    directed, direction_repaired = _repair_road_merge_directions(directed)
    directed, outdegree_pruned = _prune_road_merge_outdegree(directed)
    directed, cycle_edges_removed = _break_road_merge_cycles(directed)
    topo = _road_merge_topological_order(directed) or []
    out = {e.source: e.target for e in directed}

    batches: dict[str, list[str]] = {}
    for src in reversed(topo):
        if src not in out:
            continue
        target = _resolve_road_merge_target(src, out)
        if target == src:
            continue
        batches.setdefault(target, []).append(src)

    synth_counter = [0]
    merges_applied = 0
    anchors_created = 0
    incident_edges_remapped = 0
    source_edges_removed = 0
    for batch_index, target in enumerate(sorted(batches)):
        removed, anchors, remapped = _apply_road_merge_batch(
            graph, target, batches[target], anchor_delta_m, batch_index, synth_counter
        )
        if removed:
            merges_applied += 1
            source_edges_removed += removed
            anchors_created += anchors
            incident_edges_remapped += remapped

    return {
        "candidate_pairs": len(candidates),
        "directed_edges": len(directed),
        "direction_repaired_edges": direction_repaired,
        "outdegree_pruned_edges": outdegree_pruned,
        "cycle_edges_removed": cycle_edges_removed,
        "merge_batches_applied": merges_applied,
        "source_edges_removed": source_edges_removed,
        "anchors_created": anchors_created,
        "incident_edges_remapped": incident_edges_remapped,
        "anchor_delta_m": anchor_delta_m,
        "distance_m": max_distance_m,
        "angle_deg": max_angle_deg,
        "min_overlap_m": min_overlap_m,
        "min_overlap_ratio": min_overlap_ratio,
    }


def split_one_intersection(graph: RoadGraph, synth_counter: list[int]) -> bool:
    edge_ids_sorted = sorted(graph.edges.keys())
    rank = {eid: i for i, eid in enumerate(edge_ids_sorted)}

    refs: list[tuple[str, int]] = []
    geoms: list[LineString] = []
    for eid in edge_ids_sorted:
        e = graph.edges.get(eid)
        if e is None:
            continue
        pl = e.polyline_xy_m
        if len(pl) < 2:
            continue
        for seg_i in range(len(pl) - 1):
            a, b = pl[seg_i], pl[seg_i + 1]
            geoms.append(LineString([a, b]))
            refs.append((eid, seg_i))

    if len(geoms) < 2:
        return False

    tree = STRtree(geoms)
    raw = tree.query(np.asarray(geoms, dtype=object))
    seen_pairs: set[tuple[str, int, str, int]] = set()
    cand: list[tuple[int, int, int, int, str, str]] = []
    if raw.ndim == 2 and raw.shape[0] == 2:
        for k in range(raw.shape[1]):
            i, j = int(raw[0, k]), int(raw[1, k])
            if i >= j:
                continue
            e1, s1 = refs[i]
            e2, s2 = refs[j]
            if e1 == e2:
                continue
            if e1 > e2:
                e1, s1, e2, s2 = e2, s2, e1, s1
            pk = (e1, s1, e2, s2)
            if pk in seen_pairs:
                continue
            seen_pairs.add(pk)
            cand.append((rank[e1], rank[e2], s1, s2, e1, e2))
    cand.sort()

    for _r1, _r2, seg_i, seg_j, e1_id, e2_id in cand:
        e1 = graph.edges.get(e1_id)
        e2 = graph.edges.get(e2_id)
        if e1 is None or e2 is None:
            continue
        pl1 = e1.polyline_xy_m
        pl2 = e2.polyline_xy_m
        if len(pl1) < 2 or len(pl2) < 2:
            continue
        if seg_i >= len(pl1) - 1 or seg_j >= len(pl2) - 1:
            continue
        a, b = pl1[seg_i], pl1[seg_i + 1]
        c, d = pl2[seg_j], pl2[seg_j + 1]
        pt = segment_intersection_interior(a, b, c, d)
        if pt is None:
            continue
        if _near_any_vertex(pt, pl1) or _near_any_vertex(pt, pl2):
            continue
        _split_edge_at(graph, e1.id, pt, synth_counter)
        _split_edge_at(graph, e2.id, pt, synth_counter)
        return True
    return False


def _near_any_vertex(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    for q in poly:
        if _dist(pt, q) < SEG_PT_TOL_M * 3:
            return True
    return False


def _split_edge_at(
    graph: RoadGraph,
    edge_id: str,
    pt: tuple[float, float],
    synth_counter: list[int],
) -> None:
    e = graph.edges.get(edge_id)
    if e is None:
        return
    pl = e.polyline_xy_m
    if len(pl) < 2:
        del graph.edges[edge_id]
        return
    seg_idx: int | None = None
    best_d = 1e18
    snap_pt = pt
    for i in range(len(pl) - 1):
        proj, _t = nearest_point_on_segment(pt, pl[i], pl[i + 1])
        d = _dist(pt, proj)
        if d < best_d:
            best_d = d
            seg_idx = i
            snap_pt = proj
    if seg_idx is None or best_d > SEG_PT_TOL_M * 10:
        return
    if _dist(snap_pt, pl[seg_idx]) < SEG_PT_TOL_M * 2:
        return
    if _dist(snap_pt, pl[seg_idx + 1]) < SEG_PT_TOL_M * 2:
        return

    synth_counter[0] += 1
    new_nid = f"synth:{synth_counter[0]}"
    graph.nodes[new_nid] = InternalNode(
        id=new_nid,
        x_m=snap_pt[0],
        y_m=snap_pt[1],
        source_osm_node_ids=[],
        is_way_polyline_endpoint=False,
        merged_from_snap=False,
        merged_from_osm_id=False,
        merged_from_road_merge=False,
        synthetic_reason="intersection",
    )
    ins_at = seg_idx + 1
    pl_new = list(pl)
    pl_left = pl_new[:ins_at] + [snap_pt]
    pl_right = [snap_pt] + pl_new[ins_at:]
    if len(pl_left) < 2 or len(pl_right) < 2:
        del graph.nodes[new_nid]
        return

    del graph.edges[edge_id]
    u0, v0 = e.u, e.v
    suf = synth_counter[0]
    e_left = f"{edge_id}:L:{suf}"
    e_right = f"{edge_id}:R:{suf}"
    graph.edges[e_left] = InternalEdge(
        id=e_left,
        u=u0,
        v=new_nid,
        polyline_xy_m=_resnap_poly_to_nodes(graph, u0, new_nid, pl_left),
        osm_way_id=e.osm_way_id,
        highway=e.highway,
        merged_osm_way_ids=list(e.merged_osm_way_ids),
    )
    graph.edges[e_right] = InternalEdge(
        id=e_right,
        u=new_nid,
        v=v0,
        polyline_xy_m=_resnap_poly_to_nodes(graph, new_nid, v0, pl_right),
        osm_way_id=e.osm_way_id,
        highway=e.highway,
        merged_osm_way_ids=list(e.merged_osm_way_ids),
    )


def _resnap_poly_to_nodes(
    graph: RoadGraph,
    u: str,
    v: str,
    pl: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not pl:
        return pl
    nu = graph.nodes[u]
    nv = graph.nodes[v]
    out = list(pl)
    out[0] = (nu.x_m, nu.y_m)
    out[-1] = (nv.x_m, nv.y_m)
    return out


def run_intersection_splits(graph: RoadGraph) -> dict[str, Any]:
    synth_counter = [0]
    splits_applied = 0
    for _ in range(MAX_SPLIT_ITER):
        if not split_one_intersection(graph, synth_counter):
            break
        splits_applied += 1
    return {
        "intersection_splits_applied": splits_applied,
        "new_vertices_from_split": synth_counter[0],
    }


def _incident_edges_by_node(graph: RoadGraph) -> dict[str, list[InternalEdge]]:
    inc: dict[str, list[InternalEdge]] = {nid: [] for nid in graph.nodes}
    for e in graph.edges.values():
        if e.u in inc:
            inc[e.u].append(e)
        if e.v in inc:
            inc[e.v].append(e)
    return inc


def _node_degrees_from_incident(inc: dict[str, list[InternalEdge]]) -> dict[str, int]:
    return {nid: len(lst) for nid, lst in inc.items()}


def _other_vertex(e: InternalEdge, nid: str) -> str:
    return e.v if e.u == nid else e.u


def _edge_between_uv(graph: RoadGraph, u: str, v: str) -> InternalEdge | None:
    for e in graph.edges.values():
        if (e.u == u and e.v == v) or (e.u == v and e.v == u):
            return e
    return None


def _edges_between_uv_all(graph: RoadGraph, u: str, v: str) -> list[InternalEdge]:
    """Same undirected pair (u,v) の全辺（重複がある場合に備える）。"""
    out: list[InternalEdge] = []
    for e in graph.edges.values():
        if (e.u == u and e.v == v) or (e.u == v and e.v == u):
            out.append(e)
    return out


def _prune_vertex_protected(n: InternalNode, d: int) -> bool:
    if d != 2:
        return True
    if not n.source_osm_node_ids:
        return True
    if n.merged_from_osm_id or n.merged_from_snap:
        return True
    if n.is_way_polyline_endpoint:
        return True
    return False


def _prune_vertex_eligible(n: InternalNode, d: int, es: list[InternalEdge]) -> bool:
    if _prune_vertex_protected(n, d):
        return False
    if len(es) != 2:
        return False
    w1, w2 = es[0].osm_way_id, es[1].osm_way_id
    return w1 is not None and w1 == w2


def _signed_turn_at_vertex_rad(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> float:
    """符号付き折れ角（進行方向 P[i-1]→P[i]→P[i+1]）。退化時は 0。"""
    ux, uy = bx - ax, by - ay
    vx, vy = cx - bx, cy - by
    cu = ux * ux + uy * uy
    cv = vx * vx + vy * vy
    if cu < _PRUNE_LEN_EPS_SQ or cv < _PRUNE_LEN_EPS_SQ:
        return 0.0
    return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)


def _prune_accum_reduce_signed_mod(accum: float, threshold_rad: float) -> float:
    """|accum| から threshold の整数倍を符号方向に沿って差し引く（累積のモジュロ）。"""
    if abs(accum) < threshold_rad - 1e-15:
        return accum
    q = math.floor(abs(accum) / threshold_rad + 1e-12)
    return accum - math.copysign(q * threshold_rad, accum)


def _prune_bfs_component(
    start: str,
    eligible: dict[str, bool],
    inc: dict[str, list[InternalEdge]],
) -> set[str]:
    from collections import deque

    comp: set[str] = set()
    dq = deque([start])
    comp.add(start)
    while dq:
        cur = dq.popleft()
        for e in inc[cur]:
            o = _other_vertex(e, cur)
            if eligible.get(o) and o not in comp:
                comp.add(o)
                dq.append(o)
    return comp


def _prune_chain_ordered_endpoints(
    comp: set[str],
    inc: dict[str, list[InternalEdge]],
    eligible: dict[str, bool],
) -> list[str] | None:
    """[frozen_a, …prunable…, frozen_b] or None (pure prunable cycle — skip)."""

    def pr_nbrs(nid: str) -> list[str]:
        return [_other_vertex(e, nid) for e in inc[nid] if eligible.get(_other_vertex(e, nid), False)]

    endpoints = [nid for nid in comp if len(pr_nbrs(nid)) == 1]

    if len(comp) == 1:
        v = next(iter(comp))
        frozen = sorted(
            (_other_vertex(e, v) for e in inc[v] if not eligible.get(_other_vertex(e, v), False)),
            key=str,
        )
        if len(frozen) != 2:
            return None
        return [frozen[0], v, frozen[1]]

    if not endpoints:
        return None

    e0 = min(endpoints, key=str)
    nbr_all = [_other_vertex(e, e0) for e in inc[e0]]
    frozen_start = sorted(
        (x for x in nbr_all if not eligible.get(x, False)),
        key=str,
    )
    if not frozen_start:
        return None
    f0 = frozen_start[0]
    pr_next = [x for x in nbr_all if eligible.get(x, False)]
    if len(pr_next) != 1:
        return None

    order: list[str] = [f0, e0]
    prev, cur = f0, e0
    while True:
        nxt_cand = [_other_vertex(e, cur) for e in inc[cur] if _other_vertex(e, cur) != prev]
        if len(nxt_cand) != 1:
            return None
        nxt = nxt_cand[0]
        if not eligible.get(nxt, False):
            order.append(nxt)
            return order
        order.append(nxt)
        prev, cur = cur, nxt


def _prune_simplify_keep_indices(
    order: list[str],
    graph: RoadGraph,
    eligible: dict[str, bool],
    threshold_rad: float,
) -> list[int]:
    """元ポリライン上の符号付き折れ角を累積し、|累積| が閾値を超えた頂点を残す（1 パス）。"""
    n = len(order)
    if n < 2:
        return [0] if n else []
    if n == 2:
        return [0, 1]

    def xy(nid: str) -> tuple[float, float]:
        node = graph.nodes[nid]
        return (node.x_m, node.y_m)

    keep_ix: list[int] = [0]
    accum = 0.0
    last_i = n - 1
    for i in range(1, last_i):
        if not eligible.get(order[i], False):
            if keep_ix[-1] != i:
                keep_ix.append(i)
            accum = 0.0
            continue
        ax, ay = xy(order[i - 1])
        bx, by = xy(order[i])
        cx, cy = xy(order[i + 1])
        accum += _signed_turn_at_vertex_rad(ax, ay, bx, by, cx, cy)
        if abs(accum) >= threshold_rad - 1e-15:
            if keep_ix[-1] != i:
                keep_ix.append(i)
            accum = _prune_accum_reduce_signed_mod(accum, threshold_rad)
    if keep_ix[-1] != last_i:
        keep_ix.append(last_i)
    return keep_ix


def _prune_apply_order(
    graph: RoadGraph,
    order: list[str],
    keep_ix: list[int],
    eligible: dict[str, bool],
    eid_counter: list[int],
) -> int:
    """Returns number of prunable vertices removed."""
    keep_ids = {order[i] for i in keep_ix}
    removed = 0
    for k in range(len(keep_ix) - 1):
        lo, hi = keep_ix[k], keep_ix[k + 1]
        if hi - lo < 2:
            continue
        u0, v0 = order[lo], order[hi]
        edges_del: list[str] = []
        collapse_edges: list[InternalEdge] = []
        wid: int | None = None
        hw: str | None = None
        for t in range(lo, hi):
            a, b = order[t], order[t + 1]
            segment_edges = _edges_between_uv_all(graph, a, b)
            if not segment_edges:
                return removed
            for e in segment_edges:
                edges_del.append(e.id)
                collapse_edges.append(e)
                if wid is None:
                    wid = e.osm_way_id
                    hw = e.highway
        nu = graph.nodes[u0]
        nv = graph.nodes[v0]
        # 潰した区間は幾何的にほぼ一直線なので、表示・トポロジは端点間の 2 点折れ線に統一する
        pl = [(nu.x_m, nu.y_m), (nv.x_m, nv.y_m)]
        for eid in edges_del:
            del graph.edges[eid]
        eid_counter[0] += 1
        new_id = f"prune:{eid_counter[0]}:{u0}:{v0}"
        graph.edges[new_id] = InternalEdge(
            id=new_id,
            u=u0,
            v=v0,
            polyline_xy_m=pl,
            osm_way_id=wid,
            highway=hw,
            merged_osm_way_ids=_merge_edge_osm_way_ids(collapse_edges),
        )

    for nid in order:
        if eligible.get(nid, False) and nid not in keep_ids and nid in graph.nodes:
            del graph.nodes[nid]
            removed += 1
    return removed


def _prune_remove_edges_with_missing_endpoints(graph: RoadGraph) -> int:
    """削除済み頂点を参照している辺を除去。削除した本数を返す。"""
    bad = [eid for eid, e in graph.edges.items() if e.u not in graph.nodes or e.v not in graph.nodes]
    for eid in bad:
        del graph.edges[eid]
    return len(bad)


def prune_redundant_chain_vertices(
    graph: RoadGraph,
    accum_threshold_deg: float = DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
) -> dict[str, Any]:
    """同一 way 上の次数 2 かつ保護なしの頂点を、符号付き折れ角の累積に基づき簡略化してマージする。"""
    threshold_rad = math.radians(accum_threshold_deg)
    vertices_removed = 0
    eid_counter = [0]
    blocked: set[str] = set()

    while True:
        inc = _incident_edges_by_node(graph)
        deg = _node_degrees_from_incident(inc)
        eligible: dict[str, bool] = {}
        for nid, n in graph.nodes.items():
            if nid in blocked:
                eligible[nid] = False
                continue
            eligible[nid] = _prune_vertex_eligible(n, deg.get(nid, 0), inc.get(nid, []))

        start = next((nid for nid, ok in eligible.items() if ok), None)
        if start is None:
            break

        comp = _prune_bfs_component(start, eligible, inc)
        order = _prune_chain_ordered_endpoints(comp, inc, eligible)
        if order is None or len(order) < 3:
            blocked |= comp
            continue

        keep_ix = _prune_simplify_keep_indices(order, graph, eligible, threshold_rad)
        any_merge = any(keep_ix[k + 1] - keep_ix[k] >= 2 for k in range(len(keep_ix) - 1))
        if not any_merge:
            blocked |= comp
            continue

        vertices_removed += _prune_apply_order(graph, order, keep_ix, eligible, eid_counter)
        _prune_remove_edges_with_missing_endpoints(graph)

    _prune_remove_edges_with_missing_endpoints(graph)

    th_deg = round(accum_threshold_deg, 9)
    return {
        "vertices_removed": vertices_removed,
        "angle_accum_threshold_deg": th_deg,
    }


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
        highlight_road_merge = bool(options.merge_duplicate_roads and n.merged_from_road_merge)

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
                    "highlight_road_merge": highlight_road_merge,
                    "synthetic_reason": n.synthetic_reason,
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
    options: GraphBuildOptions,
) -> GraphBuildResult:
    step_metrics: dict[str, Any] = {}
    ways = parse_way_features(geojson_fc)

    def proj(lon: float, lat: float) -> tuple[float, float]:
        return lon_lat_to_xy_m(lon0, lat0, lon, lat)

    graph = build_native_graph(ways, proj)

    if options.connect_osm_node_ids:
        step_metrics["connect_osm"] = merge_by_osm_node_id(graph)
        step_metrics["connect_osm"]["merged_vertex_count"] = sum(
            1 for n in graph.nodes.values() if n.merged_from_osm_id
        )

    if options.snap_endpoints:
        step_metrics["snap"] = snap_endpoints(graph, options.snap_epsilon_m)

    if options.merge_duplicate_roads:
        step_metrics["road_merge"] = merge_duplicate_roads(
            graph,
            max_distance_m=options.road_merge_distance_m,
            max_angle_deg=options.road_merge_angle_deg,
            min_overlap_m=options.road_merge_min_overlap_m,
            min_overlap_ratio=options.road_merge_min_overlap_ratio,
            anchor_delta_m=options.road_merge_anchor_delta_m,
        )

    if options.split_intersections:
        step_metrics["split"] = run_intersection_splits(graph)

    if options.remove_redundant_chain_vertices:
        step_metrics["prune_chains"] = prune_redundant_chain_vertices(
            graph, options.prune_chain_accum_angle_deg
        )

    synth = sum(1 for n in graph.nodes.values() if len(n.source_osm_node_ids) == 0)
    road_merge_synth = sum(1 for n in graph.nodes.values() if n.synthetic_reason == "road_merge")
    stats = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "synthetic_node_count": synth,
        "road_merge_synthetic_node_count": road_merge_synth,
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
