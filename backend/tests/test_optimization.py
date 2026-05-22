"""最適化焼きなましロジックのテスト。"""

from __future__ import annotations

import math
import random

from app.optimization import anneal as anneal_mod
from app.optimization.anneal import (
    AnnealState,
    _effective_acceptance_temperature,
    _propose_state,
    _should_trigger_escape,
    _step_scale_at,
    simulated_annealing_search,
)
from app.optimization.candidate_select import (
    normalized_transform_dist,
    select_ranked_candidates,
)
from app.optimization.run import run_simulated_annealing
from app.optimization.scoring import score_route, shape_similarity_loss
from app.optimization.snap_route import (
    EdgeSnapIndexGrid,
    EdgeSnapIndexLinear,
    build_node_spatial_index,
    build_adjacency,
    build_route_from_polyline,
    dijkstra_path,
)
from app.optimization.transform import apply_transform, graph_center_m, stroke_to_base_polyline_m
from app.optimization.types import (
    AnnealOptions,
    OptimizeWeights,
    RestartResult,
    ScoreBreakdown,
    StrokePoint,
    TraceStep,
    Transform,
)
from app.preprocess.graph_model import InternalEdge, InternalNode, RoadGraph


def _line_graph() -> RoadGraph:
    nodes = {
        "a": InternalNode(id="a", x_m=0.0, y_m=0.0),
        "b": InternalNode(id="b", x_m=100.0, y_m=0.0),
        "c": InternalNode(id="c", x_m=200.0, y_m=0.0),
    }
    edges = {
        "e1": InternalEdge(
            id="e1",
            u="a",
            v="b",
            polyline_xy_m=[(0.0, 0.0), (100.0, 0.0)],
            osm_way_id=1,
            highway="residential",
            merged_osm_way_ids=[],
        ),
        "e2": InternalEdge(
            id="e2",
            u="b",
            v="c",
            polyline_xy_m=[(100.0, 0.0), (200.0, 0.0)],
            osm_way_id=2,
            highway="residential",
            merged_osm_way_ids=[],
        ),
    }
    return RoadGraph(nodes=nodes, edges=edges)


def test_dijkstra_line_graph() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    out = dijkstra_path(g, adj, "a", "c")
    assert out is not None
    eids, dist = out
    assert eids == ["e1", "e2"]
    assert dist > 0


def test_build_route_from_horizontal_polyline() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    poly = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, poly, arc_samples=10)
    assert route.reachable
    assert route.edge_ids == ["e1", "e2"]
    assert len(route.polyline_xy_m) >= 2


def test_multistart_simulated_annealing_trace_edge_ids() -> None:
    g = _line_graph()
    stroke = [StrokePoint(x=0.0, y=0.0), StrokePoint(x=200.0, y=0.0)]
    opt = AnnealOptions(seed=0, max_iterations=20, restart_count=2, trace_stride=2)
    result = run_simulated_annealing(
        g,
        [{"x": p.x, "y": p.y} for p in stroke],
        139.7,
        35.6,
        weights=OptimizeWeights(),
        opt=opt,
        record_trace=True,
    )
    assert len(result.restart_results) == 2
    steps = result.restart_results[result.best_restart_index].trace_steps
    assert steps
    assert len(steps) > 1
    for step in steps:
        assert step.step_index >= 0
        assert step.temperature > 0.0
        assert isinstance(step.accepted, bool)
        for eid in step.edge_ids:
            assert eid in g.edges


def test_sa_smoke_low_iterations() -> None:
    g = _line_graph()
    opt = AnnealOptions(seed=0, max_iterations=8)
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
    )
    assert result.best_score == result.best_breakdown.total(OptimizeWeights())
    assert "FeatureCollection" == result.candidates_geojson.get("type")
    assert result.optimizer_meta.get("search") == "multistart_simulated_annealing"
    assert result.optimizer_meta.get("max_iterations") == 8


def test_ignore_optimization_budget_completes_iteration_cap() -> None:
    """極小の時間予算でも ignore 時は反復上限まで進む（時間打ち切りなし）。"""
    g = _line_graph()
    n_iter = 120
    opt = AnnealOptions(
        seed=0,
        max_iterations=n_iter,
        restart_count=1,
        optimization_budget_seconds=0.05,
        ignore_optimization_budget=True,
        trace_stride=10_000,
    )
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
        record_trace=False,
    )
    assert result.optimizer_meta.get("deadline_hit") is False
    assert result.optimizer_meta.get("ignore_optimization_budget") is True
    assert result.restart_results[0].iterations_completed == n_iter


def test_optimizer_meta_multistart_simulated_annealing() -> None:
    g = _line_graph()
    opt = AnnealOptions(seed=3, max_iterations=12, restart_count=3, trace_stride=1)
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
        record_trace=True,
    )
    assert result.optimizer_meta["search"] == "multistart_simulated_annealing"
    assert result.optimizer_meta["max_iterations"] == 12
    assert result.optimizer_meta["max_iterations_per_restart"] == 12
    assert result.optimizer_meta["restart_count"] == 3
    assert len(result.restart_results) == 3
    assert result.best_restart_index in {0, 1, 2}


def test_score_route_normalized_smoke() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    poly = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, poly, arc_samples=10)
    s, bd = score_route(
        g,
        poly,
        route,
        Transform(),
        OptimizeWeights(),
    )
    assert s >= 0.0
    assert bd.unreachable == 0.0
    assert bd.shape_distance >= 0.0


def test_chamfer_shape_lower_when_route_matches_target() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    target = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, target, arc_samples=12)
    w = OptimizeWeights()
    _, bd_match = score_route(g, target, route, Transform(), w)
    _, bd_offset = score_route(
        g,
        [(50.0, 0.0), (250.0, 0.0)],
        route,
        Transform(),
        w,
    )
    assert bd_match.shape_distance < bd_offset.shape_distance


def test_stroke_to_base_polyline_flips_canvas_y_axis() -> None:
    g = _line_graph()
    stroke = [StrokePoint(x=0.0, y=0.0), StrokePoint(x=0.0, y=100.0)]
    base = stroke_to_base_polyline_m(stroke, g)
    assert base[0][1] > base[1][1]


def test_ordered_shape_loss_penalizes_reversed_route_order() -> None:
    target = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    same = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    reversed_route = list(reversed(same))
    assert shape_similarity_loss(target, same, 200.0) < shape_similarity_loss(
        target,
        reversed_route,
        200.0,
    )


def test_temperature_scaled_proposal_shrinks_step_width() -> None:
    opt = AnnealOptions(translation_step_m_ratio=0.1, rotation_step_rad=0.3, log_scale_step=0.1)
    current = AnnealState(Transform())
    wide = _propose_state(current, random.Random(2), opt, 100.0, 100.0, 1.0).transform
    narrow = _propose_state(current, random.Random(2), opt, 100.0, 100.0, 0.2).transform
    wide_mag = abs(wide.tx_m) + abs(wide.ty_m) + abs(wide.theta_rad) + abs(wide.scale - 1.0)
    narrow_mag = abs(narrow.tx_m) + abs(narrow.ty_m) + abs(narrow.theta_rad) + abs(narrow.scale - 1.0)
    assert narrow_mag < wide_mag


def test_source_rotation_penalty_prefers_input_angle() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    target = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, target, arc_samples=12)
    w = OptimizeWeights()
    _, bd_zero = score_route(g, target, route, Transform(theta_rad=0.0), w)
    _, bd_within_free_angle = score_route(
        g,
        target,
        route,
        Transform(theta_rad=math.radians(20.0)),
        w,
    )
    _, bd_at_free_limit = score_route(
        g, target, route, Transform(theta_rad=math.radians(45.0)), w,
    )
    _, bd_beyond_free = score_route(
        g, target, route, Transform(theta_rad=math.radians(60.0)), w,
    )
    assert bd_zero.source_rotation == 0.0
    assert bd_within_free_angle.source_rotation == 0.0
    assert bd_at_free_limit.source_rotation == 0.0
    assert bd_beyond_free.source_rotation > 0.0


def test_source_rotation_penalty_can_be_disabled() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    target = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, target, arc_samples=12)
    w = OptimizeWeights()
    _, bd = score_route(
        g,
        target,
        route,
        Transform(theta_rad=math.pi),
        w,
        ignore_source_rotation=True,
    )
    assert bd.source_rotation == 0.0


def _good_breakdown(shape: float = 0.1) -> ScoreBreakdown:
    return ScoreBreakdown(
        source_rotation=0.0,
        source_scale=0.0,
        shape_distance=shape,
        turn=0.0,
        unreachable=0.0,
        out_of_graph=0.0,
        dijkstra_fallback=0.0,
    )


def test_select_ranked_candidates_filters_unreachable() -> None:
    g = _line_graph()
    good = TraceStep(
        step_index=1,
        temperature=0.01,
        accepted=True,
        score_total=0.2,
        score_terms=_good_breakdown(0.1).as_dict(),
        transform={"tx_m": 0.0, "ty_m": 0.0, "theta_rad": 0.0, "scale": 1.0},
        edge_ids=["e1"],
    )
    bad = TraceStep(
        step_index=2,
        temperature=0.01,
        accepted=True,
        score_total=1e4,
        score_terms={**_good_breakdown().as_dict(), "unreachable": 1.0},
        transform={"tx_m": 0.0, "ty_m": 0.0, "theta_rad": 0.0, "scale": 1.0},
        edge_ids=[],
    )
    restarts = [
        RestartResult(
            restart_index=0,
            seed=0,
            initial_transform=Transform(),
            best_transform=Transform(),
            best_edge_ids=["e1"],
            best_polyline_xy_m=[(0.0, 0.0), (100.0, 0.0)],
            best_score=0.2,
            best_breakdown=_good_breakdown(0.1),
            best_route_length_m=100.0,
            iterations_planned=10,
            iterations_completed=10,
            accepted_moves=5,
            acceptance_rate=0.5,
            deadline_hit=False,
            trace_steps=[good, bad],
        ),
    ]
    sel = select_ranked_candidates(g, restarts, 200.0, 1.0, AnnealOptions())
    assert len(sel.ranked) == 1
    assert sel.ranked[0].tier == "best"


def test_select_ranked_candidates_dedups_same_transform() -> None:
    g = _line_graph()
    tdict = {"tx_m": 5.0, "ty_m": 0.0, "theta_rad": 0.0, "scale": 1.0}
    steps = [
        TraceStep(
            step_index=i,
            temperature=0.01,
            accepted=True,
            score_total=0.1 + i * 0.001,
            score_terms=_good_breakdown().as_dict(),
            transform=tdict,
            edge_ids=["e1"],
        )
        for i in range(5)
    ]
    restarts = [
        RestartResult(
            restart_index=0,
            seed=0,
            initial_transform=Transform(),
            best_transform=Transform(tx_m=5.0),
            best_edge_ids=["e1"],
            best_polyline_xy_m=[(0.0, 0.0), (100.0, 0.0)],
            best_score=0.1,
            best_breakdown=_good_breakdown(),
            best_route_length_m=100.0,
            iterations_planned=10,
            iterations_completed=10,
            accepted_moves=5,
            acceptance_rate=0.5,
            deadline_hit=False,
            trace_steps=steps,
        ),
    ]
    sel = select_ranked_candidates(
        g, restarts, 200.0, 1.0, AnnealOptions(candidate_diversity_min=0.12),
    )
    assert len(sel.ranked) == 1


def test_select_ranked_candidates_excludes_clearly_worse_scores() -> None:
    """include_margin 内の同率帯のみ。ベストから大きく離れた trace は出さない。"""
    g = _line_graph()
    steps = [
        TraceStep(
            step_index=0,
            temperature=0.01,
            accepted=True,
            score_total=0.0253,
            score_terms=_good_breakdown(0.02).as_dict(),
            transform={"tx_m": 0.0, "ty_m": 0.0, "theta_rad": 0.0, "scale": 1.0},
            edge_ids=["e1"],
        ),
        TraceStep(
            step_index=1,
            temperature=0.01,
            accepted=True,
            score_total=0.0370,
            score_terms=_good_breakdown(0.03).as_dict(),
            transform={"tx_m": 80.0, "ty_m": 0.0, "theta_rad": 0.5, "scale": 1.2},
            edge_ids=["e1"],
        ),
        TraceStep(
            step_index=2,
            temperature=0.01,
            accepted=True,
            score_total=0.0864,
            score_terms=_good_breakdown(0.08).as_dict(),
            transform={"tx_m": 10.0, "ty_m": 0.0, "theta_rad": 0.1, "scale": 1.0},
            edge_ids=["e1"],
        ),
    ]
    restarts = [
        RestartResult(
            restart_index=0,
            seed=0,
            initial_transform=Transform(),
            best_transform=Transform(),
            best_edge_ids=["e1"],
            best_polyline_xy_m=[(0.0, 0.0), (100.0, 0.0)],
            best_score=0.0253,
            best_breakdown=_good_breakdown(0.02),
            best_route_length_m=100.0,
            iterations_planned=10,
            iterations_completed=10,
            accepted_moves=5,
            acceptance_rate=0.5,
            deadline_hit=False,
            trace_steps=steps,
        ),
    ]
    sel = select_ranked_candidates(
        g, restarts, 200.0, 1.0, AnnealOptions(score_include_margin=0.05),
    )
    assert len(sel.ranked) <= 2
    assert all(c.score_total <= 0.0253 + 0.05 + 1e-9 for c in sel.ranked)
    assert not any(math.isclose(c.score_total, 0.0864) for c in sel.ranked)


def test_select_ranked_candidates_keeps_diverse_low_scores() -> None:
    g = _line_graph()
    transforms = [
        {"tx_m": 0.0, "ty_m": 0.0, "theta_rad": 0.0, "scale": 1.0},
        {"tx_m": 80.0, "ty_m": 0.0, "theta_rad": 0.5, "scale": 1.2},
    ]
    steps = [
        TraceStep(
            step_index=i,
            temperature=0.01,
            accepted=True,
            score_total=0.1 + i * 0.01,
            score_terms=_good_breakdown().as_dict(),
            transform=transforms[i],
            edge_ids=["e1"],
        )
        for i in range(2)
    ]
    t0 = Transform()
    t1 = Transform(tx_m=80.0, theta_rad=0.5, scale=1.2)
    assert normalized_transform_dist(t0, t1, 200.0, 1.0) >= 0.12
    restarts = [
        RestartResult(
            restart_index=0,
            seed=0,
            initial_transform=Transform(),
            best_transform=t0,
            best_edge_ids=["e1"],
            best_polyline_xy_m=[(0.0, 0.0), (100.0, 0.0)],
            best_score=0.1,
            best_breakdown=_good_breakdown(),
            best_route_length_m=100.0,
            iterations_planned=10,
            iterations_completed=10,
            accepted_moves=5,
            acceptance_rate=0.5,
            deadline_hit=False,
            trace_steps=steps,
        ),
    ]
    sel = select_ranked_candidates(
        g, restarts, 200.0, 1.0, AnnealOptions(candidate_diversity_min=0.12),
    )
    assert len(sel.ranked) == 2
    assert sel.ranked[0].tier == "best"
    assert sel.ranked[1].tier == "included"


def test_step_scale_tracks_temperature_at_cold_end() -> None:
    opt = AnnealOptions(step_scale_min=0.03)
    cold_ratio = opt.final_temperature / opt.initial_temperature
    cold_scale = _step_scale_at(cold_ratio, opt)
    assert math.isclose(cold_scale, max(0.03, cold_ratio))
    assert cold_scale < _step_scale_at(1.0, opt)
    assert math.isclose(_step_scale_at(0.02, opt), 0.03)
    # 旧式 0.2 + 0.8*sqrt(temp_ratio) より終盤は小さい
    legacy_cold = 0.2 + 0.8 * math.sqrt(cold_ratio)
    assert cold_scale < legacy_cold


def test_stagnation_escape_helpers() -> None:
    opt = AnnealOptions(initial_temperature=0.05, final_temperature=0.001)
    cold_t = opt.final_temperature
    reheat_t = _effective_acceptance_temperature(cold_t, opt, reheat_remaining=5)
    assert reheat_t > cold_t
    assert _effective_acceptance_temperature(cold_t, opt, reheat_remaining=0) == cold_t
    assert _should_trigger_escape(50, 30, 40, 25)
    assert not _should_trigger_escape(10, 30, 40, 25)
    assert not _should_trigger_escape(50, 10, 40, 25)


def test_stagnation_escape_improves_from_bad_initial(monkeypatch) -> None:
    monkeypatch.setattr(anneal_mod, "_stagnation_threshold", lambda _: 8)
    monkeypatch.setattr(anneal_mod, "_ESCAPE_COOLDOWN_STEPS", 5)
    g = _line_graph()
    stroke = [StrokePoint(x=0.0, y=0.0), StrokePoint(x=200.0, y=0.0)]
    bad_initial = Transform(tx_m=150.0, ty_m=80.0, theta_rad=1.2, scale=2.5)
    opt = AnnealOptions(
        seed=0,
        max_iterations=100,
        trace_stride=10_000,
        ignore_optimization_budget=True,
    )
    weights = OptimizeWeights()
    adj = build_adjacency(g)
    base = stroke_to_base_polyline_m(stroke, g)
    center = graph_center_m(g)
    bad_poly = apply_transform(base, bad_initial, center)
    bad_route = build_route_from_polyline(g, adj, bad_poly, arc_samples=10)
    bad_score, _ = score_route(g, bad_poly, bad_route, bad_initial, weights)

    run_with_escape = simulated_annealing_search(
        g,
        stroke,
        weights,
        opt,
        record_trace=False,
        initial_transform=bad_initial,
    )

    monkeypatch.setattr(anneal_mod, "_should_trigger_escape", lambda *args, **kwargs: False)
    run_no_escape = simulated_annealing_search(
        g,
        stroke,
        weights,
        opt,
        record_trace=False,
        initial_transform=bad_initial,
    )

    assert run_with_escape.escape_triggers >= 1
    assert run_with_escape.reheat_steps_used >= 1
    assert run_with_escape.score < bad_score
    assert run_with_escape.score < run_no_escape.score


def test_good_initial_minimal_escape(monkeypatch) -> None:
    monkeypatch.setattr(anneal_mod, "_stagnation_threshold", lambda _: 10_000)
    g = _line_graph()
    stroke = [StrokePoint(x=0.0, y=0.0), StrokePoint(x=200.0, y=0.0)]
    opt = AnnealOptions(
        seed=1,
        max_iterations=60,
        trace_stride=10_000,
        ignore_optimization_budget=True,
    )
    run = simulated_annealing_search(
        g,
        stroke,
        OptimizeWeights(),
        opt,
        record_trace=False,
        initial_transform=Transform(),
    )
    assert run.escape_triggers == 0
    assert run.score < 0.5


def test_optimizer_meta_includes_escape_counts() -> None:
    g = _line_graph()
    opt = AnnealOptions(
        seed=7,
        max_iterations=80,
        restart_count=1,
        ignore_optimization_budget=True,
        trace_stride=10_000,
    )
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 200.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
        record_trace=False,
    )
    assert "escape_triggers" in result.optimizer_meta
    assert "reheat_steps_used" in result.optimizer_meta
    assert result.optimizer_meta["escape_triggers"] == result.restart_results[0].escape_triggers


def test_multistart_each_restart_uses_full_max_iterations() -> None:
    g = _line_graph()
    opt = AnnealOptions(seed=5, max_iterations=10, restart_count=3, trace_stride=1)
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
        record_trace=True,
    )
    assert len(result.restart_results) == 3
    assert all(r.iterations_planned == 10 for r in result.restart_results)
    assert result.optimizer_meta["max_iterations_per_restart"] == 10
    for restart in result.restart_results:
        assert restart.trace_steps
        assert 0.0 <= restart.acceptance_rate <= 1.0


def test_unreachable_route_gets_large_penalty() -> None:
    g = _line_graph()
    route = build_route_from_polyline(g, {}, [(0.0, 0.0), (200.0, 0.0)], arc_samples=12)
    s, bd = score_route(g, [(0.0, 0.0), (200.0, 0.0)], route, Transform(), OptimizeWeights())
    assert bd.unreachable == 1.0
    assert s >= OptimizeWeights().unreachable


def _long_chain_graph() -> RoadGraph:
    """セグメント数が多く EdgeSnapIndexGrid を使う直線チェーン。"""
    nseg = 180
    nodes: dict[str, InternalNode] = {}
    edges: dict[str, InternalEdge] = {}
    for i in range(nseg + 1):
        nid = f"n{i}"
        nodes[nid] = InternalNode(id=nid, x_m=float(i * 5.0), y_m=0.0)
    for i in range(nseg):
        x0, x1 = float(i * 5.0), float((i + 1) * 5.0)
        edges[f"e{i}"] = InternalEdge(
            id=f"e{i}",
            u=f"n{i}",
            v=f"n{i+1}",
            polyline_xy_m=[(x0, 0.0), (x1, 0.0)],
            osm_way_id=i,
            highway="residential",
            merged_osm_way_ids=[],
        )
    return RoadGraph(nodes=nodes, edges=edges)


def test_edge_snap_grid_nearest_matches_linear() -> None:
    g = _long_chain_graph()
    linear = EdgeSnapIndexLinear(g)
    grid = EdgeSnapIndexGrid.build(g)
    assert isinstance(grid, EdgeSnapIndexGrid)
    rng = random.Random(0)
    xmax = 180 * 5.0
    for _ in range(50):
        qx = rng.uniform(-25.0, xmax + 25.0)
        qy = rng.uniform(-35.0, 35.0)
        _n1, d1 = linear.nearest(qx, qy)
        _n2, d2 = grid.nearest(qx, qy)
        assert abs(d1 - d2) < 1e-6


def test_node_spatial_index_query_bbox_matches_full_scan() -> None:
    g = _long_chain_graph()
    idx = build_node_spatial_index(g)
    lo, hi = 100.0, 250.0
    got = set(idx.query_bbox(lo, -1.0, hi, 1.0))
    expected = {nid for nid, n in g.nodes.items() if lo <= n.x_m <= hi and -1.0 <= n.y_m <= 1.0}
    assert expected <= got
