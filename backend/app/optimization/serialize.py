"""最適化結果 → dict（JSON 用）のシリアライズヘルパー。"""

from __future__ import annotations

from typing import Any

from .types import RestartResult, TraceStep, Transform


def transform_to_dict(t: Transform) -> dict[str, float]:
    return {
        "tx_m": t.tx_m,
        "ty_m": t.ty_m,
        "theta_rad": t.theta_rad,
        "scale": t.scale,
    }


def trace_step_to_dict(t: TraceStep) -> dict[str, Any]:
    d: dict[str, Any] = {
        "step_index": t.step_index,
        "temperature": t.temperature,
        "accepted": t.accepted,
        "score_total": t.score_total,
        "score_terms": t.score_terms,
        "transform": t.transform,
        "edge_ids": t.edge_ids,
    }
    if t.edge_ids_per_component:
        d["edge_ids_per_component"] = t.edge_ids_per_component
    return d


def restart_result_to_dict(r: RestartResult) -> dict[str, Any]:
    return {
        "restart_index": r.restart_index,
        "seed": r.seed,
        "initial_transform": transform_to_dict(r.initial_transform),
        "best_transform": transform_to_dict(r.best_transform),
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
        "trace_steps": [trace_step_to_dict(s) for s in r.trace_steps],
    }
