from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Any

from app.osm.projection import xy_m_to_lon_lat
from app.preprocess.graph_model import RoadGraph

from .anneal import simulated_annealing_search
from .snap_route import build_adjacency, build_edge_snap_index
from .scoring import route_geometric_length_m
from .transform import mirror_stroke_horizontal
from .types import (
    AnnealOptions,
    OptimizeResult,
    OptimizeWeights,
    RouteBuildResult,
    ScoreBreakdown,
    StrokePoint,
    TraceStep,
    Transform,
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
    """手書きストロークと道路グラフから、離散グリッドで候補ルートを 1 本返す。

    ``include_mirror_stroke`` / ``num_restarts`` により複数試行し、ベスト 1 本を返す（トレースはベスト試行のもの）。
    """
    o = opt or AnnealOptions()
    w = weights or weights_for_evaluation_mode(o.evaluation_mode)
    stroke = [StrokePoint(x=float(p["x"]), y=float(p["y"])) for p in stroke_points]

    adj = build_adjacency(graph)
    snap_index = build_edge_snap_index(graph)

    deadline = time.monotonic() + max(0.05, float(o.optimization_budget_seconds))

    strokes: list[tuple[list[StrokePoint], bool]] = [(stroke, False)]
    if o.include_mirror_stroke:
        strokes.append((mirror_stroke_horizontal(stroke), True))

    best_t: Transform | None = None
    best_route: RouteBuildResult | None = None
    best_bd: ScoreBreakdown | None = None
    best_trace: list[TraceStep] = []
    best_score = math.inf
    winning_seed = o.seed
    winning_mirror = False

    for si, (stk, _) in enumerate(strokes):
        mirrored = si == 1 and o.include_mirror_stroke
        for r in range(max(1, o.num_restarts)):
            seed_eff = o.seed + r * 10_007 + si * 131_071
            opt_r = replace(o, seed=seed_eff)
            t, route, bd, trace = simulated_annealing_search(
                graph,
                stk,
                w,
                opt_r,
                record_trace=record_trace,
                adj=adj,
                snap_index=snap_index,
                deadline=deadline,
                source_mirrored=mirrored,
            )
            total = bd.total(w)
            if total < best_score:
                best_score = total
                best_t = t
                best_route = route
                best_bd = bd
                winning_seed = seed_eff
                winning_mirror = mirrored
                if record_trace:
                    best_trace = list(trace)

    assert best_t is not None and best_route is not None and best_bd is not None

    length_m = route_geometric_length_m(graph, best_route.edge_ids)
    total_score = best_bd.total(w)
    optimizer_meta: dict[str, Any] = {
        "search": "transform_grid_search",
        "winning_seed": winning_seed,
        "stroke_mirrored": winning_mirror,
        "num_restarts": o.num_restarts,
        "include_mirror_stroke": o.include_mirror_stroke,
        "coarse_presolve": o.coarse_presolve,
        "evaluation_mode": o.evaluation_mode,
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
