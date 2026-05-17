from __future__ import annotations

import time
from typing import Any

from app.osm.projection import xy_m_to_lon_lat
from app.preprocess.graph_model import RoadGraph

from .anneal import simulated_annealing_search
from .snap_route import build_adjacency, build_edge_snap_index, build_node_spatial_index
from .scoring import route_geometric_length_m
from .types import (
    AnnealOptions,
    OptimizeResult,
    OptimizeWeights,
    StrokePoint,
    weights_for_evaluation_mode,
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


def run_simulated_annealing(
    graph: RoadGraph,
    stroke_points: list[dict[str, float]],
    lon0: float,
    lat0: float,
    weights: OptimizeWeights | None = None,
    opt: AnnealOptions | None = None,
    record_trace: bool = True,
) -> OptimizeResult:
    """手書きストロークと道路グラフから、焼きなましで候補ルートを 1 本返す。"""
    o = opt or AnnealOptions()
    w = weights or weights_for_evaluation_mode(o.evaluation_mode)
    stroke = [StrokePoint(x=float(p["x"]), y=float(p["y"])) for p in stroke_points]

    adj = build_adjacency(graph)
    snap_index = build_edge_snap_index(graph)
    node_index = build_node_spatial_index(graph)

    deadline = time.monotonic() + max(0.05, float(o.optimization_budget_seconds))

    best_t, best_route, best_bd, best_trace = simulated_annealing_search(
        graph,
        stroke,
        w,
        o,
        record_trace=record_trace,
        adj=adj,
        snap_index=snap_index,
        node_index=node_index,
        deadline=deadline,
    )

    length_m = route_geometric_length_m(graph, best_route.edge_ids)
    total_score = best_bd.total(w)
    optimizer_meta: dict[str, Any] = {
        "search": "simulated_annealing",
        "seed": o.seed,
        "evaluation_mode": o.evaluation_mode,
        "max_iterations": o.max_iterations,
        "initial_temperature": o.initial_temperature,
        "final_temperature": o.final_temperature,
        "translation_step_m_ratio": o.translation_step_m_ratio,
        "rotation_step_rad": o.rotation_step_rad,
        "log_scale_step": o.log_scale_step,
        "trace_stride": o.trace_stride,
        "optimization_budget_seconds": o.optimization_budget_seconds,
        "deadline_hit": time.monotonic() >= deadline,
    }
    props: dict[str, Any] = {
        "length_km": round(length_m / 1000.0, 6),
        "length_m": length_m,
        "edge_count": len(best_route.edge_ids),
        "score_total": total_score,
        "score_terms": best_bd.as_dict(),
        "transform": {
            "tx_m": best_t.tx_m,
            "ty_m": best_t.ty_m,
            "theta_rad": best_t.theta_rad,
            "scale": best_t.scale,
        },
        "reachable": best_route.reachable,
        "optimizer": optimizer_meta,
    }
    feat = _route_to_feature(lon0, lat0, best_route.polyline_xy_m, props)
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": [feat]}

    return OptimizeResult(
        best_transform=best_t,
        best_edge_ids=list(best_route.edge_ids),
        best_polyline_xy_m=list(best_route.polyline_xy_m),
        best_score=total_score,
        best_breakdown=best_bd,
        best_route_length_m=length_m,
        trace_steps=best_trace,
        candidates_geojson=fc,
        optimizer_meta=optimizer_meta,
    )
