"""トレース横断のランク付き候補選択（品質フィルタ・transform dedup）。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from app.preprocess.graph_model import RoadGraph

from .constants import TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN
from .scoring import route_geometric_length_m
from .snap_route import concatenate_edge_polylines
from .types import (
    AnnealOptions,
    RestartResult,
    ScoreBreakdown,
    TraceStep,
    Transform,
)

CandidateTier = Literal["best", "included"]

_LENGTH_LABEL_RATIO = 1.15


@dataclass
class TraceCandidate:
    restart_index: int
    step_index: int
    score: float
    breakdown: ScoreBreakdown
    transform: Transform
    edge_ids: list[str]
    edge_ids_per_component: list[list[str]] = field(default_factory=list)


@dataclass
class RankedCandidate:
    candidate_id: str
    rank: int
    restart_index: int
    step_index: int
    score_total: float
    score_delta_from_best: float
    tier: CandidateTier
    route_length_m: float
    transform: Transform
    edge_ids: list[str]
    edge_ids_per_component: list[list[str]]
    labels: list[str] = field(default_factory=list)
    score_terms: dict[str, float] = field(default_factory=dict)


@dataclass
class CandidateSelectionResult:
    ranked: list[RankedCandidate]
    pool_size: int
    after_quality_filter: int
    meta: dict[str, Any]


def normalized_transform_dist(
    t1: Transform,
    t2: Transform,
    span_x: float,
    span_y: float,
) -> float:
    """正規化パラメータ空間での距離（run.py の _normalized_transform_dist と同型）。"""
    raw_angle = abs(t1.theta_rad - t2.theta_rad)
    dt = min(raw_angle, 2.0 * math.pi - raw_angle) / math.pi
    log_range = math.log(max(TRANSFORM_SCALE_MAX, 1e-12)) - math.log(
        max(TRANSFORM_SCALE_MIN, 1e-12)
    )
    ds = abs(math.log(max(t1.scale, 1e-12)) - math.log(max(t2.scale, 1e-12))) / max(
        log_range, 1e-9
    )
    dx = abs(t1.tx_m - t2.tx_m) / max(2.0 * span_x, 1.0)
    dy = abs(t1.ty_m - t2.ty_m) / max(2.0 * span_y, 1.0)
    return math.sqrt(dt**2 + ds**2 + dx**2 + dy**2)


def _transform_from_dict(d: dict[str, Any]) -> Transform:
    return Transform(
        tx_m=float(d.get("tx_m", 0.0)),
        ty_m=float(d.get("ty_m", 0.0)),
        theta_rad=float(d.get("theta_rad", 0.0)),
        scale=float(d.get("scale", 1.0)),
    )


def _breakdown_from_terms(terms: dict[str, float]) -> ScoreBreakdown:
    return ScoreBreakdown(
        source_rotation=float(terms.get("source_rotation", 0.0)),
        source_scale=float(terms.get("source_scale", 0.0)),
        shape_distance=float(terms.get("shape_distance", 0.0)),
        turn=float(terms.get("turn", 0.0)),
        unreachable=float(terms.get("unreachable", 0.0)),
        out_of_graph=float(terms.get("out_of_graph", 0.0)),
        dijkstra_fallback=float(terms.get("dijkstra_fallback", 0.0)),
    )


def _has_route(c: TraceCandidate) -> bool:
    if c.edge_ids_per_component:
        return any(len(ids) > 0 for ids in c.edge_ids_per_component)
    return len(c.edge_ids) > 0


def _route_length_m(graph: RoadGraph, c: TraceCandidate) -> float:
    if c.edge_ids_per_component:
        return sum(
            route_geometric_length_m(graph, ids) for ids in c.edge_ids_per_component if ids
        )
    return route_geometric_length_m(graph, c.edge_ids)


def _is_viable(c: TraceCandidate, pool_best: float, include_margin: float) -> bool:
    if not _has_route(c):
        return False
    if c.breakdown.unreachable >= 0.5:
        return False
    if c.breakdown.dijkstra_fallback > 0.8:
        return False
    if c.score > pool_best + include_margin:
        return False
    return True


def _pool_from_restarts(restarts: list[RestartResult]) -> list[TraceCandidate]:
    pool: list[TraceCandidate] = []
    for restart in restarts:
        if restart.trace_steps:
            for step in restart.trace_steps:
                pool.append(_candidate_from_trace_step(restart.restart_index, step))
        else:
            pool.append(_candidate_from_restart_best(restart))
    return pool


def _candidate_from_trace_step(restart_index: int, step: TraceStep) -> TraceCandidate:
    terms = step.score_terms or {}
    per_comp = [list(ids) for ids in step.edge_ids_per_component]
    edge_ids = list(step.edge_ids)
    if per_comp and not edge_ids:
        edge_ids = list(per_comp[0]) if per_comp else []
    return TraceCandidate(
        restart_index=restart_index,
        step_index=step.step_index,
        score=float(step.score_total),
        breakdown=_breakdown_from_terms(terms),
        transform=_transform_from_dict(step.transform),
        edge_ids=edge_ids,
        edge_ids_per_component=per_comp,
    )


def _candidate_from_restart_best(restart: RestartResult) -> TraceCandidate:
    return TraceCandidate(
        restart_index=restart.restart_index,
        step_index=-1,
        score=restart.best_score,
        breakdown=restart.best_breakdown,
        transform=restart.best_transform,
        edge_ids=list(restart.best_edge_ids),
        edge_ids_per_component=[],
    )


def _apply_length_labels(ranked: list[RankedCandidate]) -> None:
    if len(ranked) < 2:
        return
    lengths = [c.route_length_m for c in ranked]
    lo, hi = min(lengths), max(lengths)
    if lo < 1e-9:
        return
    if hi / lo >= _LENGTH_LABEL_RATIO:
        for c in ranked:
            if math.isclose(c.route_length_m, lo, rel_tol=1e-6):
                if "compact" not in c.labels:
                    c.labels.append("compact")
            if math.isclose(c.route_length_m, hi, rel_tol=1e-6):
                if "large" not in c.labels:
                    c.labels.append("large")


def _greedy_diverse_select(
    viable: list[TraceCandidate],
    max_count: int,
    diversity_min: float,
    span_x: float,
    span_y: float,
) -> list[TraceCandidate]:
    if not viable:
        return []
    sorted_pool = sorted(viable, key=lambda c: c.score)
    selected: list[TraceCandidate] = [sorted_pool[0]]
    for cand in sorted_pool[1:]:
        if len(selected) >= max_count:
            break
        min_dist = min(
            normalized_transform_dist(cand.transform, s.transform, span_x, span_y)
            for s in selected
        )
        if min_dist >= diversity_min:
            selected.append(cand)
    return selected


def select_ranked_candidates(
    graph: RoadGraph,
    restarts: list[RestartResult],
    span_x: float,
    span_y: float,
    opt: AnnealOptions | None = None,
) -> CandidateSelectionResult:
    """全 restart の trace から表示用候補を選ぶ。"""
    o = opt or AnnealOptions()
    max_candidates = max(1, int(o.max_display_candidates))
    include_margin = max(0.0, float(o.score_include_margin))
    diversity_min = max(0.0, float(o.candidate_diversity_min))

    pool = _pool_from_restarts(restarts)
    pool_size = len(pool)
    if not pool:
        return CandidateSelectionResult(
            ranked=[],
            pool_size=0,
            after_quality_filter=0,
            meta=_selection_meta(pool_size, 0, o),
        )

    pool_best = min(c.score for c in pool)
    viable = [c for c in pool if _is_viable(c, pool_best, include_margin)]
    after_filter = len(viable)
    selected = _greedy_diverse_select(
        viable, max_candidates, diversity_min, span_x, span_y
    )

    if not selected:
        return CandidateSelectionResult(
            ranked=[],
            pool_size=pool_size,
            after_quality_filter=after_filter,
            meta=_selection_meta(pool_size, after_filter, o),
        )

    best_score = selected[0].score
    ranked: list[RankedCandidate] = []
    for rank, cand in enumerate(selected, start=1):
        cid = f"r{cand.restart_index}_s{cand.step_index}"
        ranked.append(
            RankedCandidate(
                candidate_id=cid,
                rank=rank,
                restart_index=cand.restart_index,
                step_index=cand.step_index,
                score_total=cand.score,
                score_delta_from_best=cand.score - best_score,
                tier="best" if rank == 1 else "included",
                route_length_m=_route_length_m(graph, cand),
                transform=cand.transform,
                edge_ids=list(cand.edge_ids),
                edge_ids_per_component=[list(ids) for ids in cand.edge_ids_per_component],
                score_terms=cand.breakdown.as_dict(),
            )
        )

    _apply_length_labels(ranked)
    return CandidateSelectionResult(
        ranked=ranked,
        pool_size=pool_size,
        after_quality_filter=after_filter,
        meta=_selection_meta(pool_size, after_filter, o),
    )


def _selection_meta(pool_size: int, after_filter: int, opt: AnnealOptions) -> dict[str, Any]:
    return {
        "pool_size": pool_size,
        "after_quality_filter": after_filter,
        "score_include_margin": opt.score_include_margin,
        "diversity_min": opt.candidate_diversity_min,
        "max_candidates": opt.max_display_candidates,
    }


def ranked_candidate_to_dict(c: RankedCandidate) -> dict[str, Any]:
    return {
        "candidate_id": c.candidate_id,
        "rank": c.rank,
        "restart_index": c.restart_index,
        "step_index": c.step_index,
        "score_total": c.score_total,
        "score_delta_from_best": c.score_delta_from_best,
        "tier": c.tier,
        "route_length_m": c.route_length_m,
        "route_length_km": round(c.route_length_m / 1000.0, 6),
        "transform": {
            "tx_m": c.transform.tx_m,
            "ty_m": c.transform.ty_m,
            "theta_rad": c.transform.theta_rad,
            "scale": c.transform.scale,
        },
        "edge_ids": c.edge_ids,
        "edge_ids_per_component": c.edge_ids_per_component,
        "labels": list(c.labels),
        "score_terms": dict(c.score_terms),
    }


def build_candidates_geojson(
    graph: RoadGraph,
    lon0: float,
    lat0: float,
    ranked: list[RankedCandidate],
    route_to_feature_fn: Any,
) -> dict[str, Any]:
    """採用候補ごとに Feature を生成した FeatureCollection。"""
    features: list[dict[str, Any]] = []
    for cand in ranked:
        if cand.edge_ids_per_component and len(cand.edge_ids_per_component) > 1:
            for comp_i, eids in enumerate(cand.edge_ids_per_component):
                if not eids:
                    continue
                poly = concatenate_edge_polylines(graph, eids)
                props = {
                    "candidate_id": cand.candidate_id,
                    "rank": cand.rank,
                    "component_index": comp_i,
                    "length_m": route_geometric_length_m(graph, eids),
                    "length_km": round(route_geometric_length_m(graph, eids) / 1000.0, 6),
                    "score_total": cand.score_total,
                    "tier": cand.tier,
                    "labels": list(cand.labels),
                }
                features.append(route_to_feature_fn(lon0, lat0, poly, props))
        else:
            eids = cand.edge_ids
            poly = concatenate_edge_polylines(graph, eids)
            props = {
                "candidate_id": cand.candidate_id,
                "rank": cand.rank,
                "length_m": cand.route_length_m,
                "length_km": round(cand.route_length_m / 1000.0, 6),
                "score_total": cand.score_total,
                "score_delta_from_best": cand.score_delta_from_best,
                "tier": cand.tier,
                "labels": list(cand.labels),
                "score_terms": cand.score_terms,
                "transform": {
                    "tx_m": cand.transform.tx_m,
                    "ty_m": cand.transform.ty_m,
                    "theta_rad": cand.transform.theta_rad,
                    "scale": cand.transform.scale,
                },
                "restart_index": cand.restart_index,
                "reachable": len(eids) > 0,
            }
            features.append(route_to_feature_fn(lon0, lat0, poly, props))
    return {"type": "FeatureCollection", "features": features}
