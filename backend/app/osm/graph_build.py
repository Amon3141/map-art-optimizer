"""
OSM way 折れ線から平面グラフへの変換パイプライン。

処理順（既定）:
1. ネイティブトポロジ（way 内の連続頂点間エッジ）
2. OSM node id による接続（オプション）
3. 道路交差の幾何 split（オプション）
4. 距離ベース snap（オプション）
5. 不要な中間ノード削除（オプション・上記の後のみ）
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


@dataclass
class GraphBuildOptions:
    connect_osm_node_ids: bool = False
    snap_endpoints: bool = False
    snap_epsilon_m: float = 5.0
    split_intersections: bool = False
    remove_redundant_chain_vertices: bool = False


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

# チェーン簡略化: 符号付き折れ角の累積の絶対値が約 15°（この定数）を超えた頂点をサンプルとして残す。
_PRUNE_ACCUM_THRESHOLD_RAD = math.radians(15.0)
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


# --- spatial index (H0-e: preprocess.md): Shapely STRtree ---
# Snap: index O(n log n); each node queries ε-disk neighbors via dwithin → O(log n + k).
# Split: index O(S log S) per iteration (graph mutates → rebuild); batched bbox queries.


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
        osm_merge_any = True
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=snap_any,
            merged_from_osm_id=osm_merge_any,
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
    """ε 近傍の頂点を union。点の STRtree + dwithin(ε) で候補列挙し、oid>nid のみ union。"""
    eps = max(epsilon_m, 1e-6)
    nids = list(graph.nodes.keys())
    pts = [Point(graph.nodes[i].x_m, graph.nodes[i].y_m) for i in nids]
    tree = STRtree(pts)

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
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=True,
            merged_from_osm_id=osm_merge_any,
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
        )
    graph.nodes = final_nodes
    graph.edges = new_edges
    return {
        "epsilon_m": epsilon_m,
        "snap_clusters": snap_clusters,
        "vertices_merged_by_snap": vertices_merged,
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
    )
    graph.edges[e_right] = InternalEdge(
        id=e_right,
        u=new_nid,
        v=v0,
        polyline_xy_m=_resnap_poly_to_nodes(graph, new_nid, v0, pl_right),
        osm_way_id=e.osm_way_id,
        highway=e.highway,
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
    threshold_rad: float = _PRUNE_ACCUM_THRESHOLD_RAD,
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
        wid: int | None = None
        hw: str | None = None
        for t in range(lo, hi):
            a, b = order[t], order[t + 1]
            segment_edges = _edges_between_uv_all(graph, a, b)
            if not segment_edges:
                return removed
            for e in segment_edges:
                edges_del.append(e.id)
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


def prune_redundant_chain_vertices(graph: RoadGraph) -> dict[str, Any]:
    """同一 way 上の次数 2 かつ保護なしの頂点を、符号付き折れ角の累積に基づき簡略化してマージする。"""
    vertices_removed = 0
    edges_before = len(graph.edges)
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

        keep_ix = _prune_simplify_keep_indices(order, graph, eligible)
        any_merge = any(keep_ix[k + 1] - keep_ix[k] >= 2 for k in range(len(keep_ix) - 1))
        if not any_merge:
            blocked |= comp
            continue

        vertices_removed += _prune_apply_order(graph, order, keep_ix, eligible, eid_counter)
        _prune_remove_edges_with_missing_endpoints(graph)

    _prune_remove_edges_with_missing_endpoints(graph)

    th_deg = round(math.degrees(_PRUNE_ACCUM_THRESHOLD_RAD), 9)
    return {
        "vertices_removed": vertices_removed,
        "edges_before": edges_before,
        "edges_after": len(graph.edges),
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

    if options.split_intersections:
        step_metrics["split"] = run_intersection_splits(graph)

    if options.snap_endpoints:
        step_metrics["snap"] = snap_endpoints(graph, options.snap_epsilon_m)

    if options.remove_redundant_chain_vertices:
        step_metrics["prune_chains"] = prune_redundant_chain_vertices(graph)

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
