from __future__ import annotations

import math
import random
import time
from typing import Any

from app.osm.projection import xy_m_to_lon_lat
from app.preprocess.graph_model import RoadGraph

from .constants import TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN
from .anneal import simulated_annealing_search
from .snap_route import build_adjacency, build_edge_snap_index, build_node_spatial_index
from .scoring import route_geometric_length_m
from .transform import graph_xy_bounds
from .types import (
    AnnealOptions,
    OptimizeResult,
    OptimizeWeights,
    RestartResult,
    StrokePoint,
    Transform,
)


def _route_to_feature(
    lon0: float,
    lat0: float,
    polyline_xy_m: list[tuple[float, float]],
    properties: dict[str, Any],
) -> dict[str, Any]:
    coords: list[list[float]] = []
    for x, y in polyline_xy_m:
        lon, lat = xy_m_to_lon_lat(lon0, lat0, x, y)
        coords.append([lon, lat])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": properties,
    }


def _transform_to_dict(t: Transform) -> dict[str, float]:
    return {
        "tx_m": t.tx_m,
        "ty_m": t.ty_m,
        "theta_rad": t.theta_rad,
        "scale": t.scale,
    }


def _random_initial_transform(
    rng: random.Random,
    span_x: float,
    span_y: float,
) -> Transform:
    log_min = math.log(max(TRANSFORM_SCALE_MIN, 1e-12))
    log_max = math.log(max(TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN))
    return Transform(
        tx_m=rng.uniform(-max(span_x, 1.0), max(span_x, 1.0)),
        ty_m=rng.uniform(-max(span_y, 1.0), max(span_y, 1.0)),
        theta_rad=rng.uniform(-math.pi, math.pi),
        scale=math.exp(rng.uniform(log_min, log_max)),
    )


def _restart_to_dict(r: RestartResult) -> dict[str, Any]:
    return {
        "restart_index": r.restart_index,
        "seed": r.seed,
        "initial_transform": _transform_to_dict(r.initial_transform),
        "best_transform": _transform_to_dict(r.best_transform),
        "best_edge_ids": r.best_edge_ids,
        "best_score": r.best_score,
        "best_breakdown": r.best_breakdown.as_dict(),
        "route_length_m": r.best_route_length_m,
        "route_length_km": round(r.best_route_length_m / 1000.0, 6),
        "iterations_planned": r.iterations_planned,
        "iterations_completed": r.iterations_completed,
        "accepted_moves": r.accepted_moves,
        "acceptance_rate": r.acceptance_rate,
        "deadline_hit": r.deadline_hit,
    }


def run_simulated_annealing(
    graph: RoadGraph,
    stroke_points: list[dict[str, float]],
    lon0: float,
    lat0: float,
    weights: OptimizeWeights | None = None,
    opt: AnnealOptions | None = None,
    record_trace: bool = True,
) -> OptimizeResult:
    """手書きストロークと道路グラフから、マルチスタート焼きなましで候補ルートを返す。"""
    o = opt or AnnealOptions()
    w = weights or OptimizeWeights()
    stroke = [StrokePoint(x=float(p["x"]), y=float(p["y"])) for p in stroke_points]

    adj = build_adjacency(graph)
    snap_index = build_edge_snap_index(graph)
    node_index = build_node_spatial_index(graph)

    deadline = time.monotonic() + max(0.05, float(o.optimization_budget_seconds))

    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)
    restart_count = max(1, int(o.restart_count))
    iterations_per_restart = max(0, int(o.max_iterations))
    master_rng = random.Random(o.seed)

    restart_results: list[RestartResult] = []
    for restart_index in range(restart_count):
        restart_seed = master_rng.randrange(0, 2**31)
        initial_transform = _random_initial_transform(master_rng, span_x, span_y)
        restart_opt = AnnealOptions(
            optimization_budget_seconds=o.optimization_budget_seconds,
            seed=restart_seed,
            max_iterations=iterations_per_restart,
            restart_count=1,
            ignore_source_rotation=o.ignore_source_rotation,
            initial_temperature=o.initial_temperature,
            final_temperature=o.final_temperature,
            translation_step_m_ratio=o.translation_step_m_ratio,
            rotation_step_rad=o.rotation_step_rad,
            log_scale_step=o.log_scale_step,
            trace_stride=o.trace_stride,
        )
        run = simulated_annealing_search(
            graph,
            stroke,
            w,
            restart_opt,
            record_trace=record_trace,
            initial_transform=initial_transform,
            adj=adj,
            snap_index=snap_index,
            node_index=node_index,
            deadline=deadline,
        )
        length_m = route_geometric_length_m(graph, run.route.edge_ids)
        restart_results.append(
            RestartResult(
                restart_index=restart_index,
                seed=restart_seed,
                initial_transform=initial_transform,
                best_transform=run.transform,
                best_edge_ids=list(run.route.edge_ids),
                best_polyline_xy_m=list(run.route.polyline_xy_m),
                best_score=run.score,
                best_breakdown=run.breakdown,
                best_route_length_m=length_m,
                iterations_planned=run.iterations_planned,
                iterations_completed=run.iterations_completed,
                accepted_moves=run.accepted_moves,
                acceptance_rate=run.acceptance_rate,
                deadline_hit=run.deadline_hit,
                trace_steps=run.trace_steps,
            )
        )
        if time.monotonic() >= deadline:
            break

    if not restart_results:
        raise ValueError("optimizer produced no restart results")

    best_restart = min(restart_results, key=lambda r: r.best_score)
    best_t = best_restart.best_transform
    best_bd = best_restart.best_breakdown

    length_m = best_restart.best_route_length_m
    total_score = best_bd.total(w)
    optimizer_meta: dict[str, Any] = {
        "search": "multistart_simulated_annealing",
        "seed": o.seed,
        "max_iterations": o.max_iterations,
        "max_iterations_per_restart": iterations_per_restart,
        "restart_count": restart_count,
        "restarts_completed": len(restart_results),
        "best_restart_index": best_restart.restart_index,
        "ignore_source_rotation": o.ignore_source_rotation,
        "initial_temperature": o.initial_temperature,
        "final_temperature": o.final_temperature,
        "translation_step_m_ratio": o.translation_step_m_ratio,
        "rotation_step_rad": o.rotation_step_rad,
        "log_scale_step": o.log_scale_step,
        "trace_stride": o.trace_stride,
        "optimization_budget_seconds": o.optimization_budget_seconds,
        "deadline_hit": time.monotonic() >= deadline or any(r.deadline_hit for r in restart_results),
    }
    props: dict[str, Any] = {
        "length_km": round(length_m / 1000.0, 6),
        "length_m": length_m,
        "edge_count": len(best_restart.best_edge_ids),
        "score_total": total_score,
        "score_terms": best_bd.as_dict(),
        "transform": _transform_to_dict(best_t),
        "restart_index": best_restart.restart_index,
        "reachable": len(best_restart.best_edge_ids) > 0,
        "optimizer": optimizer_meta,
    }
    feat = _route_to_feature(lon0, lat0, best_restart.best_polyline_xy_m, props)
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": [feat]}

    return OptimizeResult(
        best_transform=best_t,
        best_edge_ids=list(best_restart.best_edge_ids),
        best_polyline_xy_m=list(best_restart.best_polyline_xy_m),
        best_score=total_score,
        best_breakdown=best_bd,
        best_restart_index=best_restart.restart_index,
        best_route_length_m=length_m,
        restart_results=restart_results,
        candidates_geojson=fc,
        optimizer_meta={
            **optimizer_meta,
            "restart_summaries": [_restart_to_dict(r) for r in restart_results],
        },
    )
