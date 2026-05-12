"""Split edges at interior segment intersections."""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString

from .helpers import _dist, nearest_point_on_segment
from ..graph_model import InternalEdge, InternalNode, RoadGraph

SEG_PT_TOL_M = 0.05
PARALLEL_EPS = 1e-12
MAX_SPLIT_ITER = 2000


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


def split_one_intersection(graph: RoadGraph, synth_counter: list[int]) -> bool:
    """STRtree で候補を列挙し、最初に見つかった有効な内部交差で 1 回だけ split（HEAD モノリスと同じ）。"""
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
        p1 = _intersection_split_params(graph, e1.id, pt)
        p2 = _intersection_split_params(graph, e2.id, pt)
        if p1 is None or p2 is None:
            continue
        seg1, snap1 = p1
        seg2, snap2 = p2
        if _dist(snap1, snap2) > SEG_PT_TOL_M * 10:
            continue
        joint_xy = (
            snap1
            if _dist(snap1, snap2) < SEG_PT_TOL_M * 0.5
            else ((snap1[0] + snap2[0]) * 0.5, (snap1[1] + snap2[1]) * 0.5)
        )
        if not _intersection_split_polylines_ok(pl1, seg1, joint_xy):
            continue
        if not _intersection_split_polylines_ok(pl2, seg2, joint_xy):
            continue

        synth_counter[0] += 1
        new_nid = f"synth:{synth_counter[0]}"
        while new_nid in graph.nodes:
            synth_counter[0] += 1
            new_nid = f"synth:{synth_counter[0]}"
        suf = synth_counter[0]
        graph.nodes[new_nid] = InternalNode(
            id=new_nid,
            x_m=joint_xy[0],
            y_m=joint_xy[1],
            source_osm_node_ids=[],
            is_way_polyline_endpoint=False,
            merged_from_snap=False,
            merged_from_osm_id=False,
        )
        _split_edge_at_joint(graph, e1, seg1, joint_xy, new_nid, suf)
        _split_edge_at_joint(graph, e2, seg2, joint_xy, new_nid, suf)
        return True
    return False


def _near_any_vertex(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    for q in poly:
        if _dist(pt, q) < SEG_PT_TOL_M * 3:
            return True
    return False


def _intersection_split_params(
    graph: RoadGraph, edge_id: str, pt: tuple[float, float]
) -> tuple[int, tuple[float, float]] | None:
    """交点 pt に対する分割セグメント index と射影点。分割不可なら None。"""
    e = graph.edges.get(edge_id)
    if e is None:
        return None
    pl = e.polyline_xy_m
    if len(pl) < 2:
        return None
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
        return None
    if _dist(snap_pt, pl[seg_idx]) < SEG_PT_TOL_M * 2:
        return None
    if _dist(snap_pt, pl[seg_idx + 1]) < SEG_PT_TOL_M * 2:
        return None
    return seg_idx, snap_pt


def _intersection_split_polylines_ok(
    pl: list[tuple[float, float]], seg_idx: int, joint_xy: tuple[float, float]
) -> bool:
    ins_at = seg_idx + 1
    pl_left = pl[:ins_at] + [joint_xy]
    pl_right = [joint_xy] + pl[ins_at:]
    return len(pl_left) >= 2 and len(pl_right) >= 2


def _split_edge_at_joint(
    graph: RoadGraph,
    e: InternalEdge,
    seg_idx: int,
    joint_xy: tuple[float, float],
    new_nid: str,
    edge_suffix: int,
) -> None:
    edge_id = e.id
    pl = e.polyline_xy_m
    ins_at = seg_idx + 1
    pl_left = pl[:ins_at] + [joint_xy]
    pl_right = [joint_xy] + pl[ins_at:]
    del graph.edges[edge_id]
    u0, v0 = e.u, e.v
    e_left = f"{edge_id}:L:{edge_suffix}"
    e_right = f"{edge_id}:R:{edge_suffix}"
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
