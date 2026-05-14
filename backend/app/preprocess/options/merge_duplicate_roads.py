"""近接・ほぼ平行な重複道路（回廊）をマージする（弦ヒューリスティック + union-find）。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString

from ..defaults import (
    DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
    DEFAULT_ROAD_MERGE_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_DISTANCE_M,
    DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
)
from ..helpers import (
    _dist,
    _incident_edges_by_node,
    _merge_edge_osm_way_ids,
    nearest_point_on_segment,
)
from ..graph_model import InternalEdge, InternalNode, RoadGraph

# Union / way 集約:候補の角度緩和より厳しく見る（脇道の伝播を抑える）
ROAD_MERGE_STRICT_ANGLE_SLACK_DEG = 0.05
ROAD_MERGE_WAY_PAIR_MAX_ANGLE_EXTRA_DEG = 6.0

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


def _edge_endpoints_xy(graph: RoadGraph, e: InternalEdge) -> tuple[tuple[float, float], tuple[float, float]]:
    nu = graph.nodes[e.u]
    nv = graph.nodes[e.v]
    return (nu.x_m, nu.y_m), (nv.x_m, nv.y_m)


def _edge_length_m(graph: RoadGraph, e: InternalEdge) -> float:
    a, b = _edge_endpoints_xy(graph, e)
    return _dist(a, b)


def _road_merge_key(e: InternalEdge) -> str:
    if e.osm_way_id is not None:
        return f"way:{e.osm_way_id}"
    return f"edge:{e.id}"


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


def _segment_segment_distance_m(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> float:
    """2D 線分同士の最短距離（平面では端点–相手線分の min で十分）。"""
    return min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )


def _acute_angle_deg_between_edge_chords(graph: RoadGraph, e1: InternalEdge, e2: InternalEdge) -> float | None:
    """Chord u–v 同士の鋭角（度）。union ゲート用（角度緩和なし）。"""
    a0, a1 = _edge_endpoints_xy(graph, e1)
    b0, b1 = _edge_endpoints_xy(graph, e2)
    ax, ay = a1[0] - a0[0], a1[1] - a0[1]
    bx, by = b1[0] - b0[0], b1[1] - b0[1]
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la < 1e-6 or lb < 1e-6:
        return None
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    ang = abs(math.atan2(cross, dot))
    ang = min(ang, math.pi - ang)
    return math.degrees(ang)


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
    *,
    angle_relax: bool = True,
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
    distance_m = _segment_segment_distance_m(a0, a1, b0, b1)
    if distance_m > max_distance_m:
        return None
    overlap_ab = _parallel_overlap_m(a0, a1, b0, b1)
    overlap_ba = _parallel_overlap_m(b0, b1, a0, a1)
    overlap_m = min(overlap_ab, overlap_ba)
    required_overlap = max(min_overlap_m, min_overlap_ratio * min(la, lb))
    if overlap_m < required_overlap:
        return None
    angle_deg = _acute_angle_deg_between_edge_chords(graph, e1, e2)
    if angle_deg is None:
        return None
    endpoint_near_m = min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )
    if angle_relax:
        angle_limit = _road_merge_relaxed_angle_limit_deg(
            max_angle_deg, distance_m, max_distance_m, overlap_m, required_overlap, endpoint_near_m
        )
    else:
        angle_limit = max_angle_deg
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


def _edge_unit_vector_outward(graph: RoadGraph, e: InternalEdge, nid: str) -> tuple[float, float] | None:
    if nid not in (e.u, e.v):
        return None
    nu = graph.nodes[e.u]
    nv = graph.nodes[e.v]
    if nid == e.u:
        vx, vy = nv.x_m - nu.x_m, nv.y_m - nu.y_m
    else:
        vx, vy = nu.x_m - nv.x_m, nu.y_m - nv.y_m
    ln = math.hypot(vx, vy)
    if ln < 1e-9:
        return None
    return (vx / ln, vy / ln)


def _acute_angle_deg_unit(u1: tuple[float, float], u2: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    ang = math.degrees(math.acos(dot))
    return min(ang, 180.0 - ang)


def _road_merge_pair_ok_at_shared_node(
    graph: RoadGraph, e1: InternalEdge, e2: InternalEdge, max_angle_deg: float
) -> bool:
    """Reject unions where two edges meet at a graph node but head in very different directions (e.g. T)."""
    shared = {e1.u, e1.v} & {e2.u, e2.v}
    if not shared:
        return True
    for nid in shared:
        d1 = _edge_unit_vector_outward(graph, e1, nid)
        d2 = _edge_unit_vector_outward(graph, e2, nid)
        if d1 is None or d2 is None:
            return False
        if _acute_angle_deg_unit(d1, d2) > max_angle_deg + 0.05:
            return False
    return True


class _RoadMergeUnionFind:
    def __init__(self, edge_ids: Iterable[str]):
        self.parent: dict[str, str] = {eid: eid for eid in edge_ids}

    def find(self, x: str) -> str:
        p = self.parent.get(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb
        return True


def _road_merge_way_ok_from_grouped(
    graph: RoadGraph,
    grouped: dict[tuple[str, str], dict[str, float]],
    min_overlap_m: float,
    min_overlap_ratio: float,
    max_angle_deg: float,
) -> set[tuple[str, str]]:
    """集約メトリクスから OSM way ペアが corridor として許容されるか。"""
    out: set[tuple[str, str]] = set()
    len_by_key: dict[str, float] = {}
    for e in graph.edges.values():
        k = _road_merge_key(e)
        len_by_key[k] = len_by_key.get(k, 0.0) + _edge_length_m(graph, e)
    for (a_key, b_key), agg in grouped.items():
        len_a = len_by_key.get(a_key, 0.0)
        len_b = len_by_key.get(b_key, 0.0)
        if len_a < 1e-6 or len_b < 1e-6:
            continue
        required_overlap = max(min_overlap_m, min_overlap_ratio * min(len_a, len_b))
        if agg["overlap_m"] >= required_overlap and agg["angle_deg"] <= (
            max_angle_deg + ROAD_MERGE_WAY_PAIR_MAX_ANGLE_EXTRA_DEG
        ):
            out.add((a_key, b_key))
    return out


def _road_merge_edge_pair_candidates(
    graph: RoadGraph,
    max_distance_m: float,
    max_angle_deg: float,
    min_overlap_m: float,
    min_overlap_ratio: float,
) -> list[_RoadMergeCandidate]:
    """One candidate per undirected edge pair (best score if STRtree reports duplicates).

    Pairs that fail per-segment overlap thresholds can still be kept when their OSM-way
    aggregate overlap passes (short native segments vs. long corridor).
    """
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

    grouped: dict[tuple[str, str], dict[str, float]] = {}
    seen_way: set[tuple[str, str]] = set()
    if raw.ndim == 2 and raw.shape[0] == 2:
        for k in range(raw.shape[1]):
            i, j = int(raw[0, k]), int(raw[1, k])
            if i >= j:
                continue
            e1_id, e2_id = refs[i], refs[j]
            key = (e1_id, e2_id) if e1_id < e2_id else (e2_id, e1_id)
            if key in seen_way:
                continue
            seen_way.add(key)
            e1 = graph.edges.get(e1_id)
            e2 = graph.edges.get(e2_id)
            if e1 is None or e2 is None:
                continue
            k1 = _road_merge_key(e1)
            k2 = _road_merge_key(e2)
            if k1 == k2:
                continue
            metric = _road_merge_pair_metric(
                graph, e1, e2, max_distance_m, max_angle_deg, 0.0, 0.0, angle_relax=False
            )
            if metric is None:
                continue
            gkey = (k1, k2) if k1 < k2 else (k2, k1)
            agg = grouped.setdefault(
                gkey,
                {
                    "score": 0.0,
                    "distance_m": metric.distance_m,
                    "angle_deg": 0.0,
                    "overlap_m": 0.0,
                },
            )
            agg["score"] += metric.score
            agg["distance_m"] = min(agg["distance_m"], metric.distance_m)
            agg["angle_deg"] = max(agg["angle_deg"], metric.angle_deg)
            agg["overlap_m"] += metric.overlap_m

    way_ok = _road_merge_way_ok_from_grouped(
        graph, grouped, min_overlap_m, min_overlap_ratio, max_angle_deg
    )

    seen: set[tuple[str, str]] = set()
    best_by_pair: dict[tuple[str, str], _RoadMergeCandidate] = {}
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
            if _road_merge_key(e1) == _road_merge_key(e2):
                continue
            k1 = _road_merge_key(e1)
            k2 = _road_merge_key(e2)
            gkey = (k1, k2) if k1 < k2 else (k2, k1)
            metric = _road_merge_pair_metric(
                graph, e1, e2, max_distance_m, max_angle_deg, min_overlap_m, min_overlap_ratio
            )
            if metric is None:
                metric0 = _road_merge_pair_metric(
                    graph,
                    e1,
                    e2,
                    max_distance_m,
                    max_angle_deg,
                    0.0,
                    0.0,
                    angle_relax=False,
                )
                if metric0 is None or gkey not in way_ok:
                    continue
                metric = metric0
            prev = best_by_pair.get(key)
            if prev is None or metric.score > prev.score or (
                abs(metric.score - prev.score) < 1e-9 and (metric.a, metric.b) < (prev.a, prev.b)
            ):
                best_by_pair[key] = metric
    out = list(best_by_pair.values())
    out.sort(key=lambda c: (-c.score, c.a, c.b))
    return out


def _road_merge_union_find_from_candidates(
    graph: RoadGraph,
    candidates: list[_RoadMergeCandidate],
    max_angle_deg: float,
) -> tuple[_RoadMergeUnionFind, int]:
    uf = _RoadMergeUnionFind(graph.edges.keys())
    unions = 0
    for c in candidates:
        e1 = graph.edges.get(c.a)
        e2 = graph.edges.get(c.b)
        if e1 is None or e2 is None:
            continue
        if not _road_merge_pair_ok_at_shared_node(graph, e1, e2, max_angle_deg):
            continue
        chord_deg = _acute_angle_deg_between_edge_chords(graph, e1, e2)
        if chord_deg is None or chord_deg > max_angle_deg + ROAD_MERGE_STRICT_ANGLE_SLACK_DEG:
            continue
        if uf.union(c.a, c.b):
            unions += 1
    return uf, unions


def _road_merge_union_components(uf: _RoadMergeUnionFind, graph: RoadGraph) -> dict[str, list[str]]:
    comp: dict[str, list[str]] = {}
    for eid in sorted(graph.edges.keys()):
        r = uf.find(eid)
        comp.setdefault(r, []).append(eid)
    return comp


def _apply_road_merge_union_component(
    graph: RoadGraph,
    comp_edge_ids: list[str],
    anchor_delta_m: float,
    batch_index: int,
    synth_counter: list[int],
    max_distance_m: float,
    max_angle_deg: float,
    min_overlap_m: float,
    min_overlap_ratio: float,
    max_anchor_offset_m: float,
) -> tuple[int, int, int]:
    edges_in = [graph.edges[eid] for eid in comp_edge_ids if eid in graph.edges]
    if len(edges_in) < 2:
        return (0, 0, 0)

    by_wid: dict[int | None, list[InternalEdge]] = {}
    for e in edges_in:
        by_wid.setdefault(e.osm_way_id, []).append(e)

    nonnull_wids = [w for w in by_wid if w is not None]
    if not nonnull_wids:
        tgt = max(edges_in, key=lambda e: (_edge_length_m(graph, e), e.id))
        srcs = [e for e in edges_in if e.id != tgt.id]
        if not srcs:
            return (0, 0, 0)
        if not _preflight_source_anchor_distances(graph, tgt, srcs, max_anchor_offset_m):
            return (0, 0, 0)
        return _apply_road_merge_edge_batch(
            graph,
            tgt.id,
            sorted(s.id for s in srcs),
            anchor_delta_m,
            batch_index,
            synth_counter,
            max_anchor_offset_m,
        )

    primary_wid = max(
        nonnull_wids,
        key=lambda w: (sum(_edge_length_m(graph, e) for e in by_wid[w]), -w),
    )
    t_edges = sorted(by_wid[primary_wid], key=lambda e: e.id)
    s_edges = [e for e in edges_in if e.osm_way_id != primary_wid]
    if not s_edges:
        return (0, 0, 0)

    if len(t_edges) >= 2:
        if _ordered_chain_node_ids(t_edges) is None:
            return (0, 0, 0)
        removed, anchors, remapped = _apply_road_merge_chain_batch(
            graph,
            t_edges,
            s_edges,
            anchor_delta_m,
            batch_index,
            synth_counter,
            max_anchor_offset_m,
        )
        return (removed, anchors, remapped)

    rep = _road_merge_best_primary_target_edge(
        graph, t_edges, s_edges, min_overlap_m, min_overlap_ratio
    )
    if rep is None:
        return (0, 0, 0)
    if not _preflight_source_anchor_distances(graph, rep, s_edges, max_anchor_offset_m):
        return (0, 0, 0)
    return _apply_road_merge_edge_batch(
        graph,
        rep.id,
        sorted(e.id for e in s_edges),
        anchor_delta_m,
        batch_index,
        synth_counter,
        max_anchor_offset_m,
    )


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


def _effective_road_merge_max_anchor_offset_m(max_distance_m: float, configured: float) -> float:
    if configured > 0.0:
        return configured
    return max(2.0 * max_distance_m, 50.0)


def _road_merge_source_endpoint_points(graph: RoadGraph, edges: list[InternalEdge]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for e in edges:
        for nid in (e.u, e.v):
            n = graph.nodes[nid]
            pts.append((n.x_m, n.y_m))
    return pts


def _road_merge_source_endpoint_span_m(graph: RoadGraph, edges: list[InternalEdge]) -> float:
    pts = _road_merge_source_endpoint_points(graph, edges)
    maxd = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            maxd = max(maxd, _dist(pts[i], pts[j]))
    return maxd


def _road_merge_projection_cost_to_target(
    graph: RoadGraph, target: InternalEdge, source_edges: list[InternalEdge]
) -> tuple[float, float]:
    total = 0.0
    maxd = 0.0
    for e in source_edges:
        for nid in (e.u, e.v):
            q = (graph.nodes[nid].x_m, graph.nodes[nid].y_m)
            _h, d, _m = _nearest_point_on_polyline(q, target.polyline_xy_m)
            total += d * d
            maxd = max(maxd, d)
    return total, maxd


def _road_merge_primary_target_polyline_length_m(target: InternalEdge) -> float:
    pl = target.polyline_xy_m
    if len(pl) < 2:
        return 0.0
    return sum(_dist(pl[i], pl[i + 1]) for i in range(len(pl) - 1))


def _road_merge_best_primary_target_edge(
    graph: RoadGraph,
    t_edges: list[InternalEdge],
    s_edges: list[InternalEdge],
    min_overlap_m: float,
    min_overlap_ratio: float,
) -> InternalEdge | None:
    if not t_edges or not s_edges:
        return None
    span = _road_merge_source_endpoint_span_m(graph, s_edges)
    min_len = max(min_overlap_m, min_overlap_ratio * span) if span > 1e-6 else min_overlap_m
    best: InternalEdge | None = None
    best_key: tuple[float, float, str] | None = None
    for t in t_edges:
        L = _road_merge_primary_target_polyline_length_m(t)
        if L + 1e-9 < min_len:
            continue
        cost_sq, maxd = _road_merge_projection_cost_to_target(graph, t, s_edges)
        key = (cost_sq, maxd, t.id)
        if best is None or key < best_key:
            best = t
            best_key = key
    return best


def _preflight_source_anchor_distances(
    graph: RoadGraph,
    target: InternalEdge,
    source_edges: list[InternalEdge],
    max_anchor_offset_m: float,
) -> bool:
    pl = target.polyline_xy_m
    if len(pl) < 2:
        return False
    for e in source_edges:
        for nid in (e.u, e.v):
            q = (graph.nodes[nid].x_m, graph.nodes[nid].y_m)
            _h, d, _m = _nearest_point_on_polyline(q, pl)
            if d > max_anchor_offset_m + 1e-9:
                return False
    return True


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


def _ordered_chain_node_ids(edges: list[InternalEdge]) -> list[str] | None:
    if not edges:
        return None
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e.u, []).append(e.v)
        adj.setdefault(e.v, []).append(e.u)
    starts = sorted(n for n, ns in adj.items() if len(ns) == 1)
    start = starts[0] if starts else sorted(adj)[0]
    order = [start]
    prev: str | None = None
    cur = start
    while True:
        nxts = sorted(n for n in adj[cur] if n != prev)
        if not nxts:
            break
        nxt = nxts[0]
        if nxt in order:
            return None
        order.append(nxt)
        prev, cur = cur, nxt
    if len(order) != len(adj):
        return None
    return order


def _apply_road_merge_chain_batch(
    graph: RoadGraph,
    target_edges: list[InternalEdge],
    source_edges: list[InternalEdge],
    anchor_delta_m: float,
    batch_index: int,
    synth_counter: list[int],
    max_anchor_offset_m: float,
) -> tuple[int, int, int]:
    target_order = _ordered_chain_node_ids(target_edges)
    if target_order is None or len(target_order) < 2 or not source_edges:
        return (0, 0, 0)

    target_poly = [(graph.nodes[nid].x_m, graph.nodes[nid].y_m) for nid in target_order]
    target_stub = InternalEdge(
        id=f"roadmerge-target-chain:{batch_index}",
        u=target_order[0],
        v=target_order[-1],
        polyline_xy_m=target_poly,
        osm_way_id=target_edges[0].osm_way_id,
        highway=target_edges[0].highway,
        merged_osm_way_ids=_merge_edge_osm_way_ids(target_edges),
    )

    if not _preflight_source_anchor_distances(graph, target_stub, source_edges, max_anchor_offset_m):
        return (0, 0, 0)
    anchors: list[tuple[float, str]] = []
    acc = 0.0
    anchors.append((0.0, target_order[0]))
    for i in range(1, len(target_order)):
        acc += _dist(target_poly[i - 1], target_poly[i])
        anchors.append((acc, target_order[i]))

    source_edge_ids = {e.id for e in source_edges}
    target_edge_ids = {e.id for e in target_edges}
    source_node_ids: set[str] = set()
    anchor_for_source_node: dict[str, str] = {}
    anchors_created = 0
    for src in source_edges:
        for nid in (src.u, src.v):
            source_node_ids.add(nid)
            anchor, created = _road_merge_anchor_for_node(
                graph, target_stub, nid, anchors, anchor_delta_m, synth_counter
            )
            anchor_for_source_node[nid] = anchor
            if created:
                anchors_created += 1

    incident_remapped = 0
    delete_edges = set(source_edge_ids) | set(target_edge_ids)
    for eid, e in list(graph.edges.items()):
        if eid in delete_edges:
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

    provenance = _merge_edge_osm_way_ids(target_edges + source_edges)
    osm_way_id = target_edges[0].osm_way_id
    highway = target_edges[0].highway
    for eid in delete_edges:
        graph.edges.pop(eid, None)

    anchors_sorted: list[tuple[float, str]] = []
    seen_anchor_ids: set[str] = set()
    for measure, nid in sorted(anchors, key=lambda x: (x[0], x[1])):
        if nid in seen_anchor_ids or nid not in graph.nodes:
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
        eid = f"roadmerge:{batch_index}:{i}:chain"
        graph.edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=[(nu.x_m, nu.y_m), (nv.x_m, nv.y_m)],
            osm_way_id=osm_way_id,
            highway=highway,
            merged_osm_way_ids=provenance,
        )

    inc = _incident_edges_by_node(graph)
    for nid in source_node_ids:
        if nid in graph.nodes and not inc.get(nid):
            del graph.nodes[nid]
    return (len(source_edges), anchors_created, incident_remapped)


def _apply_road_merge_edge_batch(
    graph: RoadGraph,
    target_id: str,
    source_ids: list[str],
    anchor_delta_m: float,
    batch_index: int,
    synth_counter: list[int],
    max_anchor_offset_m: float,
) -> tuple[int, int, int]:
    target = graph.edges.get(target_id)
    if target is None:
        return (0, 0, 0)
    sources = [graph.edges[s] for s in source_ids if s in graph.edges and s != target_id]
    if not sources:
        return (0, 0, 0)

    if not _preflight_source_anchor_distances(graph, target, sources, max_anchor_offset_m):
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
    max_anchor_offset_m: float = DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
) -> dict[str, Any]:
    eff_anchor = _effective_road_merge_max_anchor_offset_m(max_distance_m, max_anchor_offset_m)
    candidates = _road_merge_edge_pair_candidates(
        graph,
        max_distance_m=max_distance_m,
        max_angle_deg=max_angle_deg,
        min_overlap_m=min_overlap_m,
        min_overlap_ratio=min_overlap_ratio,
    )
    uf, union_operations = _road_merge_union_find_from_candidates(graph, candidates, max_angle_deg)
    comp_map = _road_merge_union_components(uf, graph)
    multi_components = sorted(
        ([eid for eid in ids if eid in graph.edges] for ids in comp_map.values() if len(ids) >= 2),
        key=lambda ids: ids[0],
    )

    synth_counter = [0]
    merges_applied = 0
    skipped_merge_components = 0
    anchors_created = 0
    incident_edges_remapped = 0
    source_edges_removed = 0
    for batch_index, ids in enumerate(multi_components):
        if len(ids) < 2:
            continue
        removed, anchors, remapped = _apply_road_merge_union_component(
            graph,
            sorted(ids),
            anchor_delta_m,
            batch_index,
            synth_counter,
            max_distance_m,
            max_angle_deg,
            min_overlap_m,
            min_overlap_ratio,
            eff_anchor,
        )
        if removed:
            merges_applied += 1
            source_edges_removed += removed
            anchors_created += anchors
            incident_edges_remapped += remapped
        else:
            skipped_merge_components += 1

    return {
        "candidate_pairs": len(candidates),
        "union_operations": union_operations,
        "merge_components": len(multi_components),
        "merge_batches_applied": merges_applied,
        "skipped_merge_components": skipped_merge_components,
        "source_edges_removed": source_edges_removed,
        "anchors_created": anchors_created,
        "incident_edges_remapped": incident_edges_remapped,
        "anchor_delta_m": anchor_delta_m,
        "max_anchor_offset_m": eff_anchor,
        "distance_m": max_distance_m,
        "angle_deg": max_angle_deg,
        "min_overlap_m": min_overlap_m,
        "min_overlap_ratio": min_overlap_ratio,
    }

