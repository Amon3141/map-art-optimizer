from __future__ import annotations

import math
import time

from app.preprocess.graph_model import RoadGraph

from .constants import (
    COARSE_SCALE_MAX,
    COARSE_SCALE_MIN,
    GRID_TRANSFORM_SCALE_MAX,
    GRID_TRANSFORM_SCALE_MIN,
    GRID_TXY_FRACS,
    ROUTE_ARC_SAMPLES,
)
from .scoring import score_route
from .snap_route import (
    AnyEdgeSnapIndex,
    build_adjacency,
    build_edge_snap_index,
    build_route_from_polyline,
)
from .transform import apply_transform, graph_center_m, graph_xy_bounds, stroke_to_base_polyline_m
from .types import (
    AnnealOptions,
    OptimizeWeights,
    RouteBuildResult,
    ScoreBreakdown,
    StrokePoint,
    TraceStep,
    Transform,
)


def _clamp_scale(s: float) -> float:
    return max(GRID_TRANSFORM_SCALE_MIN, min(GRID_TRANSFORM_SCALE_MAX, s))


def _coarse_scale_tuple(scale_bins: int) -> tuple[float, ...]:
    n = max(1, scale_bins)
    lo, hi = COARSE_SCALE_MIN, COARSE_SCALE_MAX
    if lo > hi:
        lo, hi = hi, lo
    if n == 1:
        return ((lo + hi) / 2.0,)
    return tuple(lo + i * (hi - lo) / (n - 1) for i in range(n))


def _over_deadline(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


# 巨大グリッドで API レスポンスが膨らみすぎないようトレース行数を上限する
_MAX_GRID_TRACE_STEPS = 2000


def transform_grid_search(
    graph: RoadGraph,
    stroke: list[StrokePoint],
    weights: OptimizeWeights,
    opt: AnnealOptions,
    record_trace: bool = True,
    initial_transform: Transform | None = None,
    adj: dict[str, list[tuple[str, str, float]]] | None = None,
    snap_index: AnyEdgeSnapIndex | None = None,
    deadline: float | None = None,
    source_mirrored: bool = False,
) -> tuple[Transform, RouteBuildResult, ScoreBreakdown, list[TraceStep]]:
    """変換を離散グリッド上で総当たりし、スコア最小の 1 点を返す（焼きなましは使わない）。"""
    if adj is None:
        adj = build_adjacency(graph)
    if snap_index is None:
        snap_index = build_edge_snap_index(graph)
    base = stroke_to_base_polyline_m(stroke, graph)
    if len(base) < 2:
        empty = RouteBuildResult([], [], False, 0)
        z = ScoreBreakdown(0.0, 0.0, 0.0, 1e4, 1e4, 1e4, 1e4, 1.0)
        return Transform(), empty, z, []

    center = graph_center_m(graph)
    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)

    best_t = Transform()
    best_route = RouteBuildResult([], [], False, 0)
    best_bd = ScoreBreakdown(0.0, 0.0, 0.0, 1e4, 1e4, 1e4, 1e4, 1.0)
    best_score = math.inf
    trace: list[TraceStep] = []

    def consider(t: Transform) -> None:
        nonlocal best_t, best_route, best_bd, best_score
        if _over_deadline(deadline):
            return
        poly = apply_transform(base, t, center)
        route = build_route_from_polyline(graph, adj, poly, ROUTE_ARC_SAMPLES, snap_index)
        sc_v, bd = score_route(
            graph,
            poly,
            route,
            t,
            weights,
            evaluation_mode=opt.evaluation_mode,
            source_mirrored=source_mirrored,
        )
        if sc_v < best_score:
            best_score = sc_v
            best_t = Transform(t.tx_m, t.ty_m, t.theta_rad, t.scale)
            best_route = route
            best_bd = bd
            if record_trace and len(trace) < _MAX_GRID_TRACE_STEPS:
                trace.append(
                    TraceStep(
                        step_index=len(trace),
                        temperature=0.0,
                        accepted=True,
                        score_total=sc_v,
                        score_terms=bd.as_dict(),
                        transform={
                            "tx_m": best_t.tx_m,
                            "ty_m": best_t.ty_m,
                            "theta_rad": best_t.theta_rad,
                            "scale": best_t.scale,
                        },
                        edge_ids=[str(eid) for eid in route.edge_ids],
                    )
                )

    if initial_transform is not None:
        consider(
            Transform(
                initial_transform.tx_m,
                initial_transform.ty_m,
                initial_transform.theta_rad,
                initial_transform.scale,
            )
        )
    elif not opt.coarse_presolve:
        consider(Transform())
    else:
        bins = max(2, opt.coarse_theta_bins)
        scales = _coarse_scale_tuple(opt.coarse_scale_bins)
        for r in range(max(1, opt.num_restarts)):
            phase = r * (math.pi / max(8.0, float(bins) * float(max(1, opt.num_restarts))))
            for fx, fy in GRID_TXY_FRACS:
                if _over_deadline(deadline):
                    break
                for k in range(bins):
                    if _over_deadline(deadline):
                        break
                    th = k * (2.0 * math.pi / bins) + phase + opt.seed * 1e-4
                    for sc in scales:
                        if _over_deadline(deadline):
                            break
                        consider(
                            Transform(
                                tx_m=fx * span_x,
                                ty_m=fy * span_y,
                                theta_rad=th,
                                scale=_clamp_scale(float(sc)),
                            )
                        )

    return best_t, best_route, best_bd, trace


def simulated_annealing_search(
    graph: RoadGraph,
    stroke: list[StrokePoint],
    weights: OptimizeWeights,
    opt: AnnealOptions,
    record_trace: bool = True,
    initial_transform: Transform | None = None,
    adj: dict[str, list[tuple[str, str, float]]] | None = None,
    snap_index: AnyEdgeSnapIndex | None = None,
    deadline: float | None = None,
    source_mirrored: bool = False,
) -> tuple[Transform, RouteBuildResult, ScoreBreakdown, list[TraceStep]]:
    """互換名。内部は `transform_grid_search` のみ。"""
    return transform_grid_search(
        graph,
        stroke,
        weights,
        opt,
        record_trace=record_trace,
        initial_transform=initial_transform,
        adj=adj,
        snap_index=snap_index,
        deadline=deadline,
        source_mirrored=source_mirrored,
    )
