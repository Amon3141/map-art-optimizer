from __future__ import annotations

import math
import random
import time
from typing import Any

from app.osm.projection import xy_m_to_lon_lat
from app.preprocess.graph_model import RoadGraph

from .constants import ROUTE_ARC_SAMPLES, SOURCE_ROTATION_FREE_DEG, TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN
from .anneal import JointAnnealRunResult, joint_simulated_annealing_search, simulated_annealing_search
from .snap_route import (
    AnyEdgeSnapIndex,
    NodeSpatialIndexGrid,
    build_adjacency,
    build_edge_snap_index,
    build_node_spatial_index,
    build_route_from_polyline,
)
from .scoring import route_geometric_length_m, score_route
from .candidate_select import (
    build_candidates_geojson,
    ranked_candidate_to_dict,
    select_ranked_candidates,
)
from .transform import apply_transform, graph_center_m, graph_xy_bounds, stroke_to_base_polyline_m, strokes_to_base_polylines_m_shared
from .types import (
    AnnealOptions,
    ComponentOptimizeResult,
    JointOptimizeResult,
    OptimizeResult,
    OptimizeWeights,
    RestartResult,
    StrokePoint,
    Transform,
)

# グリッド探索の設定（ハードコード）
# 4×4 位置 × 3 角度 × 3 スケール = 最大 144 評価点（時間切れで打ち切り）
_GRID_POS_STEPS: int = 4        # 位置グリッドの一辺の点数（4×4 = 16 位置）
_GRID_ANGLE_STEPS: int = 3      # 角度グリッドの点数（[0, 2π/3, 4π/3] | [-π/6, 0, π/6]）
_GRID_SCALE_STEPS: int = 3      # スケール点数（log-uniform、TRANSFORM_SCALE_MIN..MAX）
_GRID_BUDGET_FRACTION: float = 0.15  # グリッド探索に充てる時間予算の割合
_DIVERSITY_FILL_TRIES: int = 10  # 補完時の diversity-aware ランダム試行数


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


def _coarse_grid_search(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    snap_index: AnyEdgeSnapIndex,
    node_index: NodeSpatialIndexGrid,
    stroke: list[StrokePoint],
    weights: OptimizeWeights,
    opt: AnnealOptions,
    span_x: float,
    span_y: float,
    grid_deadline: float,
) -> list[tuple[float, Transform]]:
    """
    (tx, ty, theta, scale) の粗いグリッドで評価し、スコア昇順の (score, transform) リストを返す。
    grid_deadline に達した時点で評価途中でも打ち切る。
    """
    base = stroke_to_base_polyline_m(stroke, graph)
    if len(base) < 2:
        return []
    center = graph_center_m(graph)

    # 位置グリッド: [-span/2, span/2] を _GRID_POS_STEPS 点で等間隔
    # ±span だとベース折れ線の中心がグラフ外に出るため半分に絞る。
    n = _GRID_POS_STEPS
    if n >= 2:
        tx_vals = [span_x * 0.5 * (-1.0 + 2.0 * i / (n - 1)) for i in range(n)]
        ty_vals = [span_y * 0.5 * (-1.0 + 2.0 * i / (n - 1)) for i in range(n)]
    else:
        tx_vals = [0.0]
        ty_vals = [0.0]

    # 角度: 回転ペナルティが有効なら無罰範囲（±SOURCE_ROTATION_FREE_DEG）周辺に集中、
    #      無効なら全方向を均等にカバーする。
    if opt.ignore_source_rotation:
        theta_vals = [2.0 * math.pi * i / max(1, _GRID_ANGLE_STEPS) for i in range(_GRID_ANGLE_STEPS)]
    else:
        free_rad = math.radians(SOURCE_ROTATION_FREE_DEG)
        theta_vals = [-free_rad, 0.0, free_rad]

    # スケール: log-uniform で _GRID_SCALE_STEPS 点
    log_min = math.log(max(TRANSFORM_SCALE_MIN, 1e-12))
    log_max = math.log(max(TRANSFORM_SCALE_MAX, TRANSFORM_SCALE_MIN))
    if _GRID_SCALE_STEPS >= 2:
        scale_vals = [
            math.exp(log_min + (log_max - log_min) * i / (_GRID_SCALE_STEPS - 1))
            for i in range(_GRID_SCALE_STEPS)
        ]
    else:
        scale_vals = [1.0]

    results: list[tuple[float, Transform]] = []
    for theta in theta_vals:
        for scale in scale_vals:
            for tx in tx_vals:
                for ty in ty_vals:
                    if time.monotonic() >= grid_deadline:
                        results.sort(key=lambda x: x[0])
                        return results
                    t = Transform(tx_m=tx, ty_m=ty, theta_rad=theta, scale=scale)
                    poly = apply_transform(base, t, center)
                    route = build_route_from_polyline(
                        graph, adj, poly, ROUTE_ARC_SAMPLES, snap_index, node_index
                    )
                    score, _ = score_route(
                        graph, poly, route, t, weights,
                        ignore_source_rotation=opt.ignore_source_rotation,
                    )
                    results.append((score, t))

    results.sort(key=lambda x: x[0])
    return results


def _normalized_transform_dist(
    t1: Transform,
    t2: Transform,
    span_x: float,
    span_y: float,
) -> float:
    """正規化パラメータ空間での距離（各次元 [0, 1] にスケール）。"""
    raw_angle = abs(t1.theta_rad - t2.theta_rad)
    dt = min(raw_angle, 2.0 * math.pi - raw_angle) / math.pi
    log_range = math.log(max(TRANSFORM_SCALE_MAX, 1e-12)) - math.log(max(TRANSFORM_SCALE_MIN, 1e-12))
    ds = abs(math.log(max(t1.scale, 1e-12)) - math.log(max(t2.scale, 1e-12))) / max(log_range, 1e-9)
    dx = abs(t1.tx_m - t2.tx_m) / max(2.0 * span_x, 1.0)
    dy = abs(t1.ty_m - t2.ty_m) / max(2.0 * span_y, 1.0)
    return math.sqrt(dt ** 2 + ds ** 2 + dx ** 2 + dy ** 2)


def _select_diverse_initial_transforms(
    candidates: list[tuple[float, Transform]],
    count: int,
    span_x: float,
    span_y: float,
) -> list[Transform]:
    """
    スコア昇順の候補リストから count 個を maximin diversity 貪欲法で選択する。
    先頭（最良スコア）を固定し、以降は既選択との最小距離が最大の候補を貪欲に選ぶ。
    """
    if not candidates:
        return []
    selected: list[Transform] = [candidates[0][1]]
    pool = [t for _, t in candidates[1:]]
    while len(selected) < count and pool:
        best_min_dist = -1.0
        best_idx = 0
        for i, t in enumerate(pool):
            min_dist = min(_normalized_transform_dist(t, s, span_x, span_y) for s in selected)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = i
        selected.append(pool.pop(best_idx))
    return selected


def _apply_ranked_candidates(
    graph: RoadGraph,
    lon0: float,
    lat0: float,
    restarts: list[RestartResult],
    span_x: float,
    span_y: float,
    opt: AnnealOptions,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """トレース横断で候補を選び GeoJSON と ranked_candidates を返す。"""
    selection = select_ranked_candidates(graph, restarts, span_x, span_y, opt)
    ranked_dicts = [ranked_candidate_to_dict(c) for c in selection.ranked]
    if selection.ranked:
        fc = build_candidates_geojson(
            graph, lon0, lat0, selection.ranked, _route_to_feature,
        )
    else:
        fc = {"type": "FeatureCollection", "features": []}
    return fc, ranked_dicts, selection.meta


def _escape_meta_from_restarts(restart_results: list[RestartResult]) -> dict[str, int]:
    return {
        "escape_triggers": sum(r.escape_triggers for r in restart_results),
        "reheat_steps_used": sum(r.reheat_steps_used for r in restart_results),
    }


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
        "escape_triggers": r.escape_triggers,
        "reheat_steps_used": r.reheat_steps_used,
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

    budget = max(0.05, float(o.optimization_budget_seconds))
    start_time = time.monotonic()
    if o.ignore_optimization_budget:
        deadline = math.inf
        grid_deadline = math.inf
    else:
        deadline = start_time + budget
        grid_deadline = start_time + budget * _GRID_BUDGET_FRACTION

    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)
    restart_count = max(1, int(o.restart_count))
    iterations_per_restart = max(0, int(o.max_iterations))

    # restart seed を先に確定（grid search より前に生成して再現性を保つ）
    master_rng = random.Random(o.seed)
    restart_seeds = [master_rng.randrange(0, 2**31) for _ in range(restart_count)]

    # 粗いグリッド探索で初期解候補を取得
    grid_candidates = _coarse_grid_search(
        graph, adj, snap_index, node_index, stroke, w, o, span_x, span_y, grid_deadline,
    )
    n_grid_candidates = len(grid_candidates)

    # スコアが極端に悪い候補（グラフ外に飛び出た等）を事前除外してから diversity 選択。
    # 最良スコアの絶対差が閾値を超えるものを落とし、残りが少なすぎる場合は上位半数を使う。
    _SCORE_FILTER_MARGIN: float = 0.5
    diverse_candidates = grid_candidates
    if grid_candidates:
        best_score = grid_candidates[0][0]
        cutoff = best_score + _SCORE_FILTER_MARGIN
        filtered = [(s, t) for s, t in grid_candidates if s <= cutoff]
        if len(filtered) >= restart_count:
            diverse_candidates = filtered
        elif len(grid_candidates) > 1:
            diverse_candidates = grid_candidates[: max(restart_count, len(grid_candidates) // 2)]

    # maximin diversity で初期解を選択
    initial_transforms = _select_diverse_initial_transforms(
        diverse_candidates, restart_count, span_x, span_y,
    )

    # 候補不足の場合は diversity-aware ランダムで補完
    while len(initial_transforms) < restart_count:
        best_t = _random_initial_transform(master_rng, span_x, span_y)
        if initial_transforms:
            best_min_dist = min(
                _normalized_transform_dist(best_t, s, span_x, span_y) for s in initial_transforms
            )
        else:
            best_min_dist = math.inf
        for _ in range(_DIVERSITY_FILL_TRIES - 1):
            t = _random_initial_transform(master_rng, span_x, span_y)
            min_dist = (
                min(_normalized_transform_dist(t, s, span_x, span_y) for s in initial_transforms)
                if initial_transforms
                else math.inf
            )
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_t = t
        initial_transforms.append(best_t)

    restart_results: list[RestartResult] = []
    for restart_index in range(restart_count):
        restart_seed = restart_seeds[restart_index]
        initial_transform = initial_transforms[restart_index]
        restart_opt = AnnealOptions(
            optimization_budget_seconds=o.optimization_budget_seconds,
            seed=restart_seed,
            max_iterations=iterations_per_restart,
            restart_count=1,
            ignore_optimization_budget=o.ignore_optimization_budget,
            ignore_source_rotation=o.ignore_source_rotation,
            initial_temperature=o.initial_temperature,
            final_temperature=o.final_temperature,
            translation_step_m_ratio=o.translation_step_m_ratio,
            rotation_step_rad=o.rotation_step_rad,
            log_scale_step=o.log_scale_step,
            trace_stride=o.trace_stride,
            step_scale_min=o.step_scale_min,
            n_local_trials=o.n_local_trials,
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
                escape_triggers=run.escape_triggers,
                reheat_steps_used=run.reheat_steps_used,
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
        "ignore_optimization_budget": o.ignore_optimization_budget,
        "deadline_hit": (not o.ignore_optimization_budget and time.monotonic() >= deadline)
        or any(r.deadline_hit for r in restart_results),
        "grid_search_candidates": n_grid_candidates,
        "grid_budget_fraction": _GRID_BUDGET_FRACTION,
        **_escape_meta_from_restarts(restart_results),
    }
    fc, ranked_dicts, selection_meta = _apply_ranked_candidates(
        graph, lon0, lat0, restart_results, span_x, span_y, o,
    )
    if ranked_dicts:
        top = ranked_dicts[0]
        br_idx = int(top["restart_index"])
        best_restart = next(
            (r for r in restart_results if r.restart_index == br_idx),
            best_restart,
        )
        best_t = best_restart.best_transform
        best_bd = best_restart.best_breakdown
        length_m = float(top.get("route_length_m", best_restart.best_route_length_m))
        total_score = float(top["score_total"])
    if not fc.get("features"):
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
        fc = {"type": "FeatureCollection", "features": [feat]}
        ranked_dicts = []

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
        ranked_candidates=ranked_dicts,
        candidate_selection_meta=selection_meta,
        optimizer_meta={
            **optimizer_meta,
            "restart_summaries": [_restart_to_dict(r) for r in restart_results],
        },
    )


# ---- ジョイント SA（マルチコンポーネント） ----

def _joint_run_to_restart_result(
    restart_index: int,
    seed: int,
    initial_transform: Transform,
    run: JointAnnealRunResult,
    graph: RoadGraph,
) -> RestartResult:
    """JointAnnealRunResult を既存の RestartResult に変換（デバッグ UI 互換）。
    スコアと breakdown は最初のコンポーネントのものを使用。"""
    from .scoring import route_geometric_length_m
    length_m = route_geometric_length_m(graph, run.routes[0].edge_ids) if run.routes else 0.0
    bd = run.breakdowns[0] if run.breakdowns else run.breakdowns[0] if run.breakdowns else None
    from .types import ScoreBreakdown
    if bd is None:
        bd = ScoreBreakdown(0.0, 0.0, 1e4, 1e4, 1e4, 1e4, 1.0)
    return RestartResult(
        restart_index=restart_index,
        seed=seed,
        initial_transform=initial_transform,
        best_transform=run.global_transform,
        best_edge_ids=list(run.routes[0].edge_ids) if run.routes else [],
        best_polyline_xy_m=list(run.routes[0].polyline_xy_m) if run.routes else [],
        best_score=run.joint_score,
        best_breakdown=bd,
        best_route_length_m=length_m,
        iterations_planned=run.iterations_planned,
        iterations_completed=run.iterations_completed,
        accepted_moves=run.accepted_moves,
        acceptance_rate=run.acceptance_rate,
        deadline_hit=run.deadline_hit,
        trace_steps=run.trace_steps,
        escape_triggers=run.escape_triggers,
        reheat_steps_used=run.reheat_steps_used,
    )


def run_joint_simulated_annealing(
    graph: RoadGraph,
    stroke_components: list[list[dict[str, float]]],
    lon0: float,
    lat0: float,
    weights: OptimizeWeights | None = None,
    opt: AnnealOptions | None = None,
    record_trace: bool = True,
) -> JointOptimizeResult:
    """複数コンポーネントをジョイント焼きなましで最適化し、JointOptimizeResult を返す。"""
    o = opt or AnnealOptions()
    w = weights or OptimizeWeights()

    components = [
        [StrokePoint(x=float(p["x"]), y=float(p["y"])) for p in comp]
        for comp in stroke_components
    ]

    adj = build_adjacency(graph)
    snap_index = build_edge_snap_index(graph)
    node_index = build_node_spatial_index(graph)

    budget = max(0.05, float(o.optimization_budget_seconds))
    start_time = time.monotonic()
    if o.ignore_optimization_budget:
        deadline = math.inf
        grid_deadline = math.inf
    else:
        deadline = start_time + budget
        grid_deadline = start_time + budget * _GRID_BUDGET_FRACTION

    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    span_x = max(gx1 - gx0, 1.0)
    span_y = max(gy1 - gy0, 1.0)
    restart_count = max(1, int(o.restart_count))
    iterations_per_restart = max(0, int(o.max_iterations))

    # 全コンポーネント共有スケールの base polyline を生成
    base_polylines = strokes_to_base_polylines_m_shared(components, graph)

    # グリッド探索は最大 arc length のコンポーネントで実施
    from .anneal import _polyline_arc_length
    arc_lengths = [_polyline_arc_length(bp) for bp in base_polylines]
    base_idx = int(max(range(len(arc_lengths)), key=lambda i: arc_lengths[i]))
    base_stroke = components[base_idx]

    master_rng = random.Random(o.seed)
    restart_seeds = [master_rng.randrange(0, 2**31) for _ in range(restart_count)]

    grid_candidates = _coarse_grid_search(
        graph, adj, snap_index, node_index, base_stroke, w, o, span_x, span_y, grid_deadline,
    )
    n_grid_candidates = len(grid_candidates)

    _SCORE_FILTER_MARGIN: float = 0.5
    diverse_candidates = grid_candidates
    if grid_candidates:
        best_score = grid_candidates[0][0]
        cutoff = best_score + _SCORE_FILTER_MARGIN
        filtered = [(s, t) for s, t in grid_candidates if s <= cutoff]
        if len(filtered) >= restart_count:
            diverse_candidates = filtered
        elif len(grid_candidates) > 1:
            diverse_candidates = grid_candidates[: max(restart_count, len(grid_candidates) // 2)]

    initial_transforms = _select_diverse_initial_transforms(
        diverse_candidates, restart_count, span_x, span_y,
    )
    while len(initial_transforms) < restart_count:
        best_t = _random_initial_transform(master_rng, span_x, span_y)
        if initial_transforms:
            best_min_dist = min(
                _normalized_transform_dist(best_t, s, span_x, span_y) for s in initial_transforms
            )
        else:
            best_min_dist = math.inf
        for _ in range(_DIVERSITY_FILL_TRIES - 1):
            t = _random_initial_transform(master_rng, span_x, span_y)
            min_dist = (
                min(_normalized_transform_dist(t, s, span_x, span_y) for s in initial_transforms)
                if initial_transforms else math.inf
            )
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_t = t
        initial_transforms.append(best_t)

    restart_results: list[RestartResult] = []
    best_run: JointAnnealRunResult | None = None

    for restart_index in range(restart_count):
        restart_seed = restart_seeds[restart_index]
        initial_transform = initial_transforms[restart_index]
        restart_opt = AnnealOptions(
            optimization_budget_seconds=o.optimization_budget_seconds,
            seed=restart_seed,
            max_iterations=iterations_per_restart,
            restart_count=1,
            ignore_optimization_budget=o.ignore_optimization_budget,
            ignore_source_rotation=o.ignore_source_rotation,
            initial_temperature=o.initial_temperature,
            final_temperature=o.final_temperature,
            translation_step_m_ratio=o.translation_step_m_ratio,
            rotation_step_rad=o.rotation_step_rad,
            log_scale_step=o.log_scale_step,
            trace_stride=o.trace_stride,
            step_scale_min=o.step_scale_min,
            n_local_trials=o.n_local_trials,
        )
        run = joint_simulated_annealing_search(
            graph,
            base_polylines,
            w,
            restart_opt,
            record_trace=record_trace,
            initial_transform=initial_transform,
            adj=adj,
            snap_index=snap_index,
            node_index=node_index,
            deadline=deadline,
        )
        restart_results.append(
            _joint_run_to_restart_result(restart_index, restart_seed, initial_transform, run, graph)
        )
        if best_run is None or run.joint_score < best_run.joint_score:
            best_run = run
        if time.monotonic() >= deadline:
            break

    if best_run is None:
        raise ValueError("joint optimizer produced no results")

    # 各コンポーネントの結果を ComponentOptimizeResult にまとめる
    from .scoring import route_geometric_length_m
    comp_results: list[ComponentOptimizeResult] = []
    merged_features: list[Any] = []
    for i, (route, bd) in enumerate(zip(best_run.routes, best_run.breakdowns)):
        length_m = route_geometric_length_m(graph, route.edge_ids)
        w_score = bd.total(w)
        comp_results.append(ComponentOptimizeResult(
            component_index=i,
            best_edge_ids=list(route.edge_ids),
            best_polyline_xy_m=list(route.polyline_xy_m),
            best_score=w_score,
            best_breakdown=bd,
            route_length_m=length_m,
        ))
        props: dict[str, Any] = {
            "component_index": i,
            "length_km": round(length_m / 1000.0, 6),
            "length_m": length_m,
            "score_total": w_score,
            "score_terms": bd.as_dict(),
        }
        merged_features.append(_route_to_feature(lon0, lat0, route.polyline_xy_m, props))

    merged_fc: dict[str, Any] = {"type": "FeatureCollection", "features": merged_features}

    candidates_fc, ranked_dicts, selection_meta = _apply_ranked_candidates(
        graph, lon0, lat0, restart_results, span_x, span_y, o,
    )
    if candidates_fc.get("features"):
        merged_fc = candidates_fc

    best_joint_score = best_run.joint_score
    if ranked_dicts:
        best_joint_score = float(ranked_dicts[0]["score_total"])

    best_restart = min(restart_results, key=lambda r: r.best_score)
    optimizer_meta: dict[str, Any] = {
        "search": "joint_multistart_simulated_annealing",
        "seed": o.seed,
        "max_iterations": o.max_iterations,
        "max_iterations_per_restart": iterations_per_restart,
        "restart_count": restart_count,
        "restarts_completed": len(restart_results),
        "best_restart_index": best_restart.restart_index,
        "ignore_source_rotation": o.ignore_source_rotation,
        "initial_temperature": o.initial_temperature,
        "final_temperature": o.final_temperature,
        "optimization_budget_seconds": o.optimization_budget_seconds,
        "ignore_optimization_budget": o.ignore_optimization_budget,
        "deadline_hit": (not o.ignore_optimization_budget and time.monotonic() >= deadline)
            or any(r.deadline_hit for r in restart_results),
        "grid_search_candidates": n_grid_candidates,
        "grid_budget_fraction": _GRID_BUDGET_FRACTION,
        "n_components": len(stroke_components),
        **_escape_meta_from_restarts(restart_results),
        "restart_summaries": [_restart_to_dict(r) for r in restart_results],
    }

    return JointOptimizeResult(
        components=comp_results,
        best_joint_score=best_joint_score,
        best_transform=best_run.global_transform,
        best_local_offsets=best_run.local_offsets,
        candidates_geojson=merged_fc,
        ranked_candidates=ranked_dicts,
        candidate_selection_meta=selection_meta,
        restart_results=restart_results,
        optimizer_meta=optimizer_meta,
    )
