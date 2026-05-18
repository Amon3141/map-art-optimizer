from __future__ import annotations

import math
import random

from app.optimization.anneal import AnnealState, _propose_state
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
from app.optimization.transform import stroke_to_base_polyline_m
from app.optimization.types import AnnealOptions, OptimizeWeights, StrokePoint, Transform
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
    _, bd_rotated = score_route(g, target, route, Transform(theta_rad=math.radians(45.0)), w)
    assert bd_zero.source_rotation == 0.0
    assert bd_within_free_angle.source_rotation == 0.0
    assert bd_zero.source_rotation < bd_rotated.source_rotation


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
