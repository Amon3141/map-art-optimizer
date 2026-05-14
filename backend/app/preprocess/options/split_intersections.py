"""線分同士の内部交差で辺を分割する。"""

from __future__ import annotations

from typing import Any

from shapely import STRtree
from shapely.geometry import LineString, Point

from ..helpers import _dist, nearest_point_on_segment
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


def _segment_bbox_disjoint(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    minx1, maxx1 = min(ax, bx), max(ax, bx)
    miny1, maxy1 = min(ay, by), max(ay, by)
    minx2, maxx2 = min(cx, dx), max(cx, dx)
    miny2, maxy2 = min(cy, dy), max(cy, dy)
    return maxx1 < minx2 or maxx2 < minx1 or maxy1 < miny2 or maxy2 < miny1


def _as_int_indices(hits: Any) -> list[int]:
    """STRtree.query の戻りを整数インデックスのリストに統一する。"""
    if hits is None:
        return []
    if hasattr(hits, "ndim") and getattr(hits, "ndim", 0) == 2 and hits.shape[0] >= 1:
        hits = hits[0]
    if hasattr(hits, "tolist"):
        hits = hits.tolist()
    if isinstance(hits, (list, tuple)):
        return [int(x) for x in hits]
    return [int(hits)]


def _near_any_vertex_spatial(
    pt: tuple[float, float],
    edge_id: str,
    _poly: list[tuple[float, float]],
    v_tree: STRtree | None,
    v_edge: list[str],
    tol: float,
) -> bool:
    """当該辺の頂点のみ、点索引で近傍検索（全頂点スキャン回避）。"""
    if v_tree is None:
        return False
    hits = v_tree.query(Point(pt), predicate="dwithin", distance=tol)
    for vi in _as_int_indices(hits):
        if 0 <= vi < len(v_edge) and v_edge[vi] == edge_id:
            return True
    return False


def split_one_intersection(graph: RoadGraph, synth_counter: list[int]) -> bool:
    """STRtree で候補を列挙し、最初に見つかった有効な内部交差で 1 回だけ split（HEAD モノリスと同じ）。"""
    edge_ids_sorted = sorted(graph.edges.keys())

    refs: list[tuple[str, int]] = []
    geoms: list[LineString] = []
    v_geoms: list[Point] = []
    v_edge: list[str] = []
    for eid in edge_ids_sorted:
        e = graph.edges.get(eid)
        if e is None:
            continue
        pl = e.polyline_xy_m
        if len(pl) < 2:
            continue
        for q in pl:
            v_geoms.append(Point(q))
            v_edge.append(eid)
        for seg_i in range(len(pl) - 1):
            a, b = pl[seg_i], pl[seg_i + 1]
            geoms.append(LineString([a, b]))
            refs.append((eid, seg_i))

    if len(geoms) < 2:
        return False

    tree = STRtree(geoms)
    v_tree = STRtree(v_geoms) if v_geoms else None
    v_tol = SEG_PT_TOL_M * 3

    seen_pairs: set[tuple[str, int, str, int]] = set()
    n = len(geoms)
    for i in range(n):
        hits = tree.query(geoms[i], predicate="intersects")
        js = sorted(set(_as_int_indices(hits)))
        for j in js:
            if j <= i:
                continue
            e1_id, s1 = refs[i]
            e2_id, s2 = refs[j]
            if e1_id == e2_id:
                continue
            if e1_id > e2_id:
                e1_id, s1, e2_id, s2 = e2_id, s2, e1_id, s1
            pk = (e1_id, s1, e2_id, s2)
            if pk in seen_pairs:
                continue
            seen_pairs.add(pk)

            e1 = graph.edges.get(e1_id)
            e2 = graph.edges.get(e2_id)
            if e1 is None or e2 is None:
                continue
            pl1 = e1.polyline_xy_m
            pl2 = e2.polyline_xy_m
            if len(pl1) < 2 or len(pl2) < 2:
                continue
            if s1 >= len(pl1) - 1 or s2 >= len(pl2) - 1:
                continue
            a, b = pl1[s1], pl1[s1 + 1]
            c, d = pl2[s2], pl2[s2 + 1]
            if _segment_bbox_disjoint(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]):
                continue
            pt = segment_intersection_interior(a, b, c, d)
            if pt is None:
                continue
            if _near_any_vertex_spatial(pt, e1_id, pl1, v_tree, v_edge, v_tol) or _near_any_vertex_spatial(
                pt, e2_id, pl2, v_tree, v_edge, v_tol
            ):
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
