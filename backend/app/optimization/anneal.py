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
    AnnealRunResult,
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


_MOVE_TYPES = ("translate", "rotate", "scale")

# Basin hopping: 高温期にこの確率でランダムリセットを試みる
_JUMP_PROBABILITY: float = 0.05
_JUMP_TEMP_THRESHOLD: float = 0.5


def _random_transform(rng: random.Random, span_x: float, span_y: float) -> Transform:
    """span 内で一様ランダムな変換を生成（basin hopping 用）。"""
    log_min = math.log(max(TRANSFORM_SCALE_MIN, 1e-12))
    log_max = math.log(max(TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN))
    return Transform(
        tx_m=rng.uniform(-max(span_x, 1.0), max(span_x, 1.0)),
        ty_m=rng.uniform(-max(span_y, 1.0), max(span_y, 1.0)),
        theta_rad=rng.uniform(-math.pi, math.pi),
        scale=math.exp(rng.uniform(log_min, log_max)),
    )


def _apply_single_move(
    t: Transform,
    move: str,
    rng: random.Random,
    opt: AnnealOptions,
    span_x: float,
    span_y: float,
    step_scale: float,
) -> None:
    """t を in-place で 1 種類の摂動を適用する。"""
    if move == "translate":
        step_x = max(1.0, span_x) * max(0.0, opt.translation_step_m_ratio) * step_scale
        step_y = max(1.0, span_y) * max(0.0, opt.translation_step_m_ratio) * step_scale
        t.tx_m = _clamp_shift(t.tx_m + rng.gauss(0.0, step_x), span_x)
        t.ty_m = _clamp_shift(t.ty_m + rng.gauss(0.0, step_y), span_y)
    elif move == "rotate":
        t.theta_rad += rng.gauss(0.0, max(0.0, opt.rotation_step_rad) * step_scale)
    else:  # scale
        log_scale = math.log(max(t.scale, 1e-12)) + rng.gauss(
            0.0,
            max(0.0, opt.log_scale_step) * step_scale,
        )
        t.scale = _clamp_scale(math.exp(log_scale))


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

    # 1/4 の確率で compound move（3 種から 2 種をランダムに選んで同時摂動）
    move_type = rng.choice((*_MOVE_TYPES, "compound"))
    if move_type == "compound":
        moves = rng.sample(_MOVE_TYPES, 2)
    else:
        moves = (move_type,)

    for move in moves:
        _apply_single_move(next_t, move, rng, opt, span_x, span_y, step_scale)

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
) -> AnnealRunResult:
    """スナップ元の変換パラメータを状態にした 1 restart 分の焼きなまし。"""
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
        return AnnealRunResult(
            transform=Transform(),
            route=empty,
            breakdown=z,
            score=z.total(weights),
            trace_steps=[],
            iterations_planned=0,
            iterations_completed=0,
            accepted_moves=0,
            deadline_hit=_over_deadline(deadline),
        )

    center = graph_center_m(graph)
    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)
    rng = random.Random(opt.seed)
    max_iterations = max(0, int(opt.max_iterations))
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
            ignore_source_rotation=opt.ignore_source_rotation,
        )
        return EvaluatedState(state, route, breakdown, score)

    initial_state = AnnealState(initial_transform or Transform())
    current = evaluate(initial_state)
    best = current
    trace: list[TraceStep] = []
    iterations_completed = 0
    accepted_moves = 0
    if record_trace:
        _record_trace_step(trace, 0, _temperature_at(0, max_iterations, opt), True, current)

    for step in range(1, max_iterations + 1):
        if _over_deadline(deadline):
            break

        iterations_completed += 1
        temperature = _temperature_at(step - 1, max_iterations, opt)
        temp_ratio = temperature / max(float(opt.initial_temperature), 1e-12)
        step_scale = 0.2 + 0.8 * math.sqrt(max(0.0, min(1.0, temp_ratio)))
        # Basin hopping: 高温期に低確率でランダムリセットを提案する
        if temp_ratio > _JUMP_TEMP_THRESHOLD and rng.random() < _JUMP_PROBABILITY:
            proposal_state = AnnealState(_random_transform(rng, span_x, span_y))
        else:
            proposal_state = _propose_state(current.state, rng, opt, span_x, span_y, step_scale)
        proposal = evaluate(proposal_state)
        delta = proposal.score - current.score
        accepted = delta <= 0.0
        if not accepted:
            probability = math.exp(-delta / max(temperature, 1e-12))
            accepted = rng.random() < probability

        if accepted:
            accepted_moves += 1
            current = proposal
            if current.score < best.score:
                best = current

        best_updated = accepted and current is best
        should_record = record_trace and (step % trace_stride == 0 or best_updated)
        if should_record:
            _record_trace_step(trace, step, temperature, accepted, current)

    return AnnealRunResult(
        transform=best.state.transform,
        route=best.route,
        breakdown=best.breakdown,
        score=best.score,
        trace_steps=trace,
        iterations_planned=max_iterations,
        iterations_completed=iterations_completed,
        accepted_moves=accepted_moves,
        deadline_hit=_over_deadline(deadline),
    )
