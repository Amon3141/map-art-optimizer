from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from app.preprocess.graph_model import RoadGraph

from .constants import ROUTE_ARC_SAMPLES, TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN
from .scoring import score_route
from .snap_route import (
    AnyEdgeSnapIndex,
    NodeSpatialIndexGrid,
    build_adjacency,
    build_edge_snap_index,
    build_node_spatial_index,
    build_route_from_polyline,
)
from .transform import (
    apply_transform,
    graph_center_m,
    graph_xy_bounds,
    stroke_to_base_polyline_m,
)
from .types import (
    AnnealOptions,
    OptimizeWeights,
    RouteBuildResult,
    ScoreBreakdown,
    StrokePoint,
    TraceStep,
    Transform,
)


@dataclass
class AnnealState:
    transform: Transform


@dataclass
class EvaluatedState:
    state: AnnealState
    route: RouteBuildResult
    breakdown: ScoreBreakdown
    score: float


def _over_deadline(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _clamp_scale(scale: float) -> float:
    return max(TRANSFORM_SCALE_MIN, min(TRANSFORM_SCALE_MAX, scale))


def _clamp_shift(v: float, span_m: float) -> float:
    limit = max(1.0, span_m)
    return max(-limit, min(limit, v))


def _temperature_at(step_index: int, max_iterations: int, opt: AnnealOptions) -> float:
    if max_iterations <= 1:
        return max(opt.final_temperature, 1e-12)
    t0 = max(float(opt.initial_temperature), 1e-12)
    t1 = max(float(opt.final_temperature), 1e-12)
    frac = step_index / float(max_iterations - 1)
    return t0 * ((t1 / t0) ** frac)


def _transform_dict(state: AnnealState) -> dict[str, float | bool]:
    return {
        "tx_m": state.transform.tx_m,
        "ty_m": state.transform.ty_m,
        "theta_rad": state.transform.theta_rad,
        "scale": state.transform.scale,
    }


def _record_trace_step(
    trace: list[TraceStep],
    step_index: int,
    temperature: float,
    accepted: bool,
    evaluated: EvaluatedState,
) -> None:
    trace.append(
        TraceStep(
            step_index=step_index,
            temperature=temperature,
            accepted=accepted,
            score_total=evaluated.score,
            score_terms=evaluated.breakdown.as_dict(),
            transform=_transform_dict(evaluated.state),
            edge_ids=[str(eid) for eid in evaluated.route.edge_ids],
        )
    )


def _propose_state(
    current: AnnealState,
    rng: random.Random,
    opt: AnnealOptions,
    span_x: float,
    span_y: float,
    step_scale: float,
) -> AnnealState:
    t = current.transform
    next_t = Transform(t.tx_m, t.ty_m, t.theta_rad, t.scale)

    move = rng.choice(("translate", "rotate", "scale"))
    if move == "translate":
        step_x = max(1.0, span_x) * max(0.0, opt.translation_step_m_ratio) * step_scale
        step_y = max(1.0, span_y) * max(0.0, opt.translation_step_m_ratio) * step_scale
        next_t.tx_m = _clamp_shift(next_t.tx_m + rng.gauss(0.0, step_x), span_x)
        next_t.ty_m = _clamp_shift(next_t.ty_m + rng.gauss(0.0, step_y), span_y)
    elif move == "rotate":
        next_t.theta_rad += rng.gauss(0.0, max(0.0, opt.rotation_step_rad) * step_scale)
    else:
        log_scale = math.log(max(next_t.scale, 1e-12)) + rng.gauss(
            0.0,
            max(0.0, opt.log_scale_step) * step_scale,
        )
        next_t.scale = _clamp_scale(math.exp(log_scale))

    return AnnealState(next_t)


def simulated_annealing_search(
    graph: RoadGraph,
    stroke: list[StrokePoint],
    weights: OptimizeWeights,
    opt: AnnealOptions,
    record_trace: bool = True,
    initial_transform: Transform | None = None,
    adj: dict[str, list[tuple[str, str, float]]] | None = None,
    snap_index: AnyEdgeSnapIndex | None = None,
    node_index: NodeSpatialIndexGrid | None = None,
    deadline: float | None = None,
) -> tuple[Transform, RouteBuildResult, ScoreBreakdown, list[TraceStep]]:
    """スナップ元の変換パラメータを状態にした単一スタート焼きなまし。"""
    if adj is None:
        adj = build_adjacency(graph)
    if snap_index is None:
        snap_index = build_edge_snap_index(graph)
    if node_index is None:
        node_index = build_node_spatial_index(graph)

    base = stroke_to_base_polyline_m(stroke, graph)
    if len(base) < 2:
        empty = RouteBuildResult([], [], False, 0)
        z = ScoreBreakdown(0.0, 0.0, 1e4, 1e4, 1e4, 1e4, 1.0)
        return Transform(), empty, z, []

    center = graph_center_m(graph)
    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)
    rng = random.Random(opt.seed)
    max_iterations = max(1, int(opt.max_iterations))
    trace_stride = max(1, int(opt.trace_stride))

    def evaluate(state: AnnealState) -> EvaluatedState:
        poly = apply_transform(base, state.transform, center)
        route = build_route_from_polyline(graph, adj, poly, ROUTE_ARC_SAMPLES, snap_index, node_index)
        score, breakdown = score_route(
            graph,
            poly,
            route,
            state.transform,
            weights,
            evaluation_mode=opt.evaluation_mode,
        )
        return EvaluatedState(state, route, breakdown, score)

    initial_state = AnnealState(initial_transform or Transform())
    current = evaluate(initial_state)
    best = current
    trace: list[TraceStep] = []
    if record_trace:
        _record_trace_step(trace, 0, _temperature_at(0, max_iterations, opt), True, current)

    for step in range(1, max_iterations + 1):
        if _over_deadline(deadline):
            break

        temperature = _temperature_at(step - 1, max_iterations, opt)
        temp_ratio = temperature / max(float(opt.initial_temperature), 1e-12)
        step_scale = 0.2 + 0.8 * math.sqrt(max(0.0, min(1.0, temp_ratio)))
        proposal_state = _propose_state(current.state, rng, opt, span_x, span_y, step_scale)
        proposal = evaluate(proposal_state)
        delta = proposal.score - current.score
        accepted = delta <= 0.0
        if not accepted:
            probability = math.exp(-delta / max(temperature, 1e-12))
            accepted = rng.random() < probability

        if accepted:
            current = proposal
            if current.score < best.score:
                best = current

        best_updated = accepted and current is best
        should_record = record_trace and (step % trace_stride == 0 or best_updated)
        if should_record:
            _record_trace_step(trace, len(trace), temperature, accepted, current)

    return best.state.transform, best.route, best.breakdown, trace
