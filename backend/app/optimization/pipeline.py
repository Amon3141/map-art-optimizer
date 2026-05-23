"""道路グラフ上での焼きなまし実行と API レスポンス組み立て。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.preprocess.graph_model import RoadGraph

from .run import run_joint_simulated_annealing, run_simulated_annealing
from .serialize import restart_result_to_dict
from .types import AnnealOptions, JointOptimizeResult, OptimizeResult, OptimizeWeights


def _components_response(components: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "component_index": c.component_index,
            "best_score": c.best_score,
            "best_breakdown": c.best_breakdown.as_dict(),
            "route_length_m": c.route_length_m,
            "route_length_km": round(c.route_length_m / 1000.0, 6),
        }
        for c in components
    ]


def _joint_response(joint_result: JointOptimizeResult, *, include_debug_fields: bool) -> dict[str, Any]:
    total_length_m = sum(c.route_length_m for c in joint_result.components)
    rep_bd = joint_result.components[0].best_breakdown if joint_result.components else None
    out: dict[str, Any] = {
        "candidates_geojson": joint_result.candidates_geojson,
        "ranked_candidates": joint_result.ranked_candidates,
        "best_score": joint_result.best_joint_score,
        "best_breakdown": rep_bd.as_dict() if rep_bd else {},
        "best_restart_index": min(
            range(len(joint_result.restart_results)),
            key=lambda i: joint_result.restart_results[i].best_score,
            default=0,
        ),
        "route_length_m": total_length_m,
        "route_length_km": round(total_length_m / 1000.0, 6),
        "restarts": [restart_result_to_dict(r) for r in joint_result.restart_results],
        "components": _components_response(joint_result.components),
    }
    if include_debug_fields:
        out["candidate_selection_meta"] = joint_result.candidate_selection_meta
        out["optimizer_meta"] = joint_result.optimizer_meta
    return out


def _single_response(opt_result: OptimizeResult, *, include_debug_fields: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "candidates_geojson": opt_result.candidates_geojson,
        "ranked_candidates": opt_result.ranked_candidates,
        "best_score": opt_result.best_score,
        "best_breakdown": opt_result.best_breakdown.as_dict(),
        "best_restart_index": opt_result.best_restart_index,
        "route_length_m": opt_result.best_route_length_m,
        "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
        "restarts": [restart_result_to_dict(r) for r in opt_result.restart_results],
        "components": [
            {
                "component_index": 0,
                "best_score": opt_result.best_score,
                "best_breakdown": opt_result.best_breakdown.as_dict(),
                "route_length_m": opt_result.best_route_length_m,
                "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
            }
        ],
    }
    if include_debug_fields:
        out["candidate_selection_meta"] = opt_result.candidate_selection_meta
        out["optimizer_meta"] = opt_result.optimizer_meta
    return out


def run_optimization_pipeline(
    graph: RoadGraph,
    lon0: float,
    lat0: float,
    stroke_components: list[list[dict[str, float]]],
    *,
    weights: OptimizeWeights | None = None,
    anneal: AnnealOptions | None = None,
    record_trace: bool = True,
    should_cancel: Callable[[], bool] | None = None,
    include_debug_fields: bool = False,
) -> dict[str, Any]:
    """
    stroke_components（各点は {"x", "y"}）から焼きなましを実行し、API 共通フィールドを返す。
    空の stroke_components は ValueError。
    """
    if len(stroke_components) < 1:
        raise ValueError("stroke_components must be non-empty")

    w = weights or OptimizeWeights()
    opt = anneal or AnnealOptions()

    if len(stroke_components) > 1:
        joint_result = run_joint_simulated_annealing(
            graph,
            stroke_components,
            lon0,
            lat0,
            weights=w,
            opt=opt,
            record_trace=record_trace,
            should_cancel=should_cancel,
        )
        return _joint_response(joint_result, include_debug_fields=include_debug_fields)

    opt_result = run_simulated_annealing(
        graph,
        stroke_components[0],
        lon0,
        lat0,
        weights=w,
        opt=opt,
        record_trace=record_trace,
        should_cancel=should_cancel,
    )
    return _single_response(opt_result, include_debug_fields=include_debug_fields)
