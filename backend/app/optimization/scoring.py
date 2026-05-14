from __future__ import annotations

import math

from app.preprocess.graph_model import RoadGraph
from app.preprocess.helpers import nearest_point_on_segment

from .constants import ROUTE_ARC_SAMPLES
from .snap_route import edge_geometric_length_m, sample_polyline_arc_length
from .transform import graph_bbox_diagonal_m
from .types import OptimizeWeights, RouteBuildResult, ScoreBreakdown


def mean_sq_dist_samples_to_polyline(
    samples: list[tuple[float, float]],
    polyline: list[tuple[float, float]],
) -> float:
    """各サンプルから polyline セグメントへの最短距離の二乗の平均。"""
    if not samples:
        return 0.0
    if len(polyline) < 2:
        return 1e12
    total = 0.0
    for q in samples:
        best = math.inf
        for i in range(len(polyline) - 1):
            a, b = polyline[i], polyline[i + 1]
            pt, _t = nearest_point_on_segment(q, a, b)
            best = min(best, math.hypot(pt[0] - q[0], pt[1] - q[1]))
        total += best * best
    return total / len(samples)


def route_geometric_length_m(graph: RoadGraph, edge_ids: list[str]) -> float:
    t = 0.0
    for eid in edge_ids:
        e = graph.edges.get(eid)
        if e is None:
            continue
        t += edge_geometric_length_m(e)
    return t


def turn_penalty_from_polyline(route_polyline: list[tuple[float, float]]) -> float:
    """隣接セグメント間の折れ角（ラジアン）の絶対値和。"""
    if len(route_polyline) < 3:
        return 0.0
    pen = 0.0
    for i in range(1, len(route_polyline) - 1):
        ax, ay = route_polyline[i - 1]
        bx, by = route_polyline[i]
        cx, cy = route_polyline[i + 1]
        v1x, v1y = bx - ax, by - ay
        v2x, v2y = cx - bx, cy - by
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cr = (v1x * v2y - v1y * v2x) / (l1 * l2)
        dt = (v1x * v2x + v1y * v2y) / (l1 * l2)
        ang = abs(math.atan2(cr, dt))
        pen += ang
    return pen


def _unreachable_breakdown(target_length_m: float | None) -> ScoreBreakdown:
    big = 1e4
    len_term = big if target_length_m is not None else 0.0
    return ScoreBreakdown(
        shape=big,
        length=len_term,
        edge_count=big,
        turn=big,
        unreachable=1.0,
    )


def score_route(
    graph: RoadGraph,
    target_polyline_xy_m: list[tuple[float, float]],
    route: RouteBuildResult,
    target_length_m: float | None,
    weights: OptimizeWeights,
) -> tuple[float, ScoreBreakdown]:
    diag_m = graph_bbox_diagonal_m(graph)
    if not route.reachable or len(route.edge_ids) == 0:
        bd = _unreachable_breakdown(target_length_m)
        return bd.total(weights), bd

    n_sc = ROUTE_ARC_SAMPLES
    chamfer_pts = sample_polyline_arc_length(target_polyline_xy_m, n_sc)
    chamfer_msq = mean_sq_dist_samples_to_polyline(chamfer_pts, route.polyline_xy_m)
    shape_term = math.sqrt(max(0.0, chamfer_msq)) / max(diag_m, 1.0)

    rlen = route_geometric_length_m(graph, route.edge_ids)
    raw_excess = 0.0
    if target_length_m is not None:
        raw_excess = max(0.0, abs(rlen - float(target_length_m)))

    if target_length_m is None:
        length_term = 0.0
    else:
        len_scale = max(float(target_length_m), diag_m * 0.05, 1.0)
        length_term = raw_excess / len_scale

    n_edges = len(route.edge_ids)
    turn_raw = turn_penalty_from_polyline(route.polyline_xy_m)
    edge_term = float(n_edges) / max(1, ROUTE_ARC_SAMPLES)
    n_turn_denom = max(1, len(route.polyline_xy_m) - 2)
    turn_term = turn_raw / (math.pi * float(n_turn_denom))

    bd = ScoreBreakdown(
        shape=shape_term,
        length=length_term,
        edge_count=edge_term,
        turn=turn_term,
        unreachable=0.0,
    )
    return bd.total(weights), bd
