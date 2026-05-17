from __future__ import annotations

import math

from app.preprocess.graph_model import RoadGraph
from app.preprocess.helpers import nearest_point_on_segment

from .constants import ROUTE_ARC_SAMPLES
from .snap_route import edge_geometric_length_m, sample_polyline_arc_length
from .transform import graph_bbox_diagonal_m
from .types import OptimizeWeights, RouteBuildResult, ScoreBreakdown, Transform


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


def _mean_sq_dist_polyline_to_polyline_samples(
    source_polyline: list[tuple[float, float]],
    target_polyline: list[tuple[float, float]],
    n_samples: int,
) -> float:
    samples = sample_polyline_arc_length(source_polyline, n_samples)
    return mean_sq_dist_samples_to_polyline(samples, target_polyline)


def shape_similarity_loss(
    target_polyline_xy_m: list[tuple[float, float]],
    route_polyline_xy_m: list[tuple[float, float]],
    diag_m: float,
) -> float:
    """スナップ元とルートの双方向チャンファー距離（bbox 対角で無次元化）。"""
    target_to_route = _mean_sq_dist_polyline_to_polyline_samples(
        target_polyline_xy_m,
        route_polyline_xy_m,
        ROUTE_ARC_SAMPLES,
    )
    route_to_target = _mean_sq_dist_polyline_to_polyline_samples(
        route_polyline_xy_m,
        target_polyline_xy_m,
        ROUTE_ARC_SAMPLES,
    )
    rms = math.sqrt(max(0.0, 0.5 * (target_to_route + route_to_target)))
    return rms / max(diag_m, 1.0)


def _normalized_rotation_abs(theta_rad: float) -> float:
    wrapped = (theta_rad + math.pi) % (2.0 * math.pi) - math.pi
    return abs(wrapped) / math.pi


def score_source_transform(
    transform: Transform,
    source_mirrored: bool,
    evaluation_mode: str,
) -> tuple[float, float, float]:
    """スナップ元そのものの評価項。小さいほど入力の向き・好みに近い。"""
    source_rotation = _normalized_rotation_abs(transform.theta_rad)
    if evaluation_mode == "elegant":
        source_scale = max(0.0, transform.scale)
    else:
        source_scale = abs(math.log(max(transform.scale, 1e-9)))
    source_mirror = 1.0 if source_mirrored else 0.0
    return source_rotation, source_scale, source_mirror


def _unreachable_breakdown(
    transform: Transform,
    source_mirrored: bool,
    evaluation_mode: str,
) -> ScoreBreakdown:
    big = 1e4
    source_rotation, source_scale, source_mirror = score_source_transform(
        transform,
        source_mirrored,
        evaluation_mode,
    )
    return ScoreBreakdown(
        source_rotation=source_rotation,
        source_scale=source_scale,
        source_mirror=source_mirror,
        shape_distance=big,
        route_length=big,
        edge_count=big,
        turn=big,
        unreachable=1.0,
    )


def score_route(
    graph: RoadGraph,
    target_polyline_xy_m: list[tuple[float, float]],
    route: RouteBuildResult,
    transform: Transform,
    weights: OptimizeWeights,
    evaluation_mode: str = "faithful",
    source_mirrored: bool = False,
) -> tuple[float, ScoreBreakdown]:
    diag_m = graph_bbox_diagonal_m(graph)
    source_rotation, source_scale, source_mirror = score_source_transform(
        transform,
        source_mirrored,
        evaluation_mode,
    )
    if not route.reachable or len(route.edge_ids) == 0:
        bd = _unreachable_breakdown(transform, source_mirrored, evaluation_mode)
        return bd.total(weights), bd

    rlen = route_geometric_length_m(graph, route.edge_ids)
    n_edges = len(route.edge_ids)
    turn_raw = turn_penalty_from_polyline(route.polyline_xy_m)
    shape_term = shape_similarity_loss(target_polyline_xy_m, route.polyline_xy_m, diag_m)
    route_length_term = rlen / max(diag_m, 1.0)
    edge_term = float(n_edges) / max(1, ROUTE_ARC_SAMPLES)
    n_turn_denom = max(1, len(route.polyline_xy_m) - 2)
    turn_term = turn_raw / (math.pi * float(n_turn_denom))

    bd = ScoreBreakdown(
        source_rotation=source_rotation,
        source_scale=source_scale,
        source_mirror=source_mirror,
        shape_distance=shape_term,
        route_length=route_length_term,
        edge_count=edge_term,
        turn=turn_term,
        unreachable=0.0,
    )
    return bd.total(weights), bd
