from __future__ import annotations

import random

from app.optimization.run import run_simulated_annealing
from app.optimization.scoring import score_route
from app.optimization.snap_route import (
    EdgeSnapIndexGrid,
    EdgeSnapIndexLinear,
    build_adjacency,
    build_route_from_polyline,
    dijkstra_path,
)
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


def test_simulated_annealing_trace_edge_ids() -> None:
    g = _line_graph()
    # 対角ストロークは多くの格子点で到達不能のままになりトレースが 1 件に留まりやすい。
    # 水平ストローク + seed=0 はグリッド中で複数回ベスト更新が起きる。
    stroke = [StrokePoint(x=0.0, y=0.0), StrokePoint(x=200.0, y=0.0)]
    opt = AnnealOptions(seed=0)
    result = run_simulated_annealing(
        g,
        [{"x": p.x, "y": p.y} for p in stroke],
        139.7,
        35.6,
        weights=OptimizeWeights(),
        opt=opt,
        record_trace=True,
    )
    steps = result.trace_steps
    assert steps
    assert len(steps) > 1
    for i, step in enumerate(steps):
        assert step.step_index == i
        for eid in step.edge_ids:
            assert eid in g.edges
    for i in range(len(steps) - 1):
        assert steps[i].score_total > steps[i + 1].score_total

def test_sa_smoke_low_iterations() -> None:
    g = _line_graph()
    opt = AnnealOptions(seed=0)
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
    )
    assert result.best_score == result.best_breakdown.total(OptimizeWeights())
    assert "FeatureCollection" == result.candidates_geojson.get("type")
    assert result.optimizer_meta.get("num_restarts") == 1


def test_multirestart_and_mirror_merge_meta() -> None:
    g = _line_graph()
    opt = AnnealOptions(
        seed=3,
        num_restarts=2,
        include_mirror_stroke=True,
        coarse_presolve=False,
    )
    result = run_simulated_annealing(
        g,
        [{"x": 0.0, "y": 0.0}, {"x": 20.0, "y": 0.0}],
        0.0,
        0.0,
        opt=opt,
    )
    assert result.optimizer_meta["num_restarts"] == 2
    assert result.optimizer_meta["include_mirror_stroke"] is True
    assert result.optimizer_meta.get("search") == "transform_grid_search"
    assert isinstance(result.optimizer_meta.get("winning_seed"), int)


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


def test_source_rotation_penalty_prefers_input_angle() -> None:
    g = _line_graph()
    adj = build_adjacency(g)
    target = [(0.0, 0.0), (200.0, 0.0)]
    route = build_route_from_polyline(g, adj, target, arc_samples=12)
    w = OptimizeWeights()
    _, bd_zero = score_route(g, target, route, Transform(theta_rad=0.0), w)
    _, bd_rotated = score_route(g, target, route, Transform(theta_rad=1.0), w)
    assert bd_zero.source_rotation < bd_rotated.source_rotation


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
