"""Graph build metrics and node visualization metadata."""

import time

import math

from app.osm.graph_build import (
    GraphBuildOptions,
    apply_all_graph_build_options,
    build_graph_from_geojson,
    build_native_graph,
    graph_to_geojson_fc,
    parse_way_features,
)
from app.osm.projection import EARTH_RADIUS_M, xy_m_to_lon_lat


def _graph_opts_road_merge_for_compact_fixtures(**kwargs) -> GraphBuildOptions:
    """狭い間隔の並列線フィクスチャ用。UI 既定（重なり 100m 等）では候補が出ない。"""
    base: dict = {
        "merge_duplicate_roads": True,
        "road_merge_distance_m": 14.0,
        "road_merge_min_overlap_m": 8.0,
        "road_merge_min_overlap_ratio": 0.25,
    }
    base.update(kwargs)
    return GraphBuildOptions(**base)


def test_prune_collinear_chain_reduces_graph():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 0], [0.001, 0], [0.002, 0], [0.003, 0], [0.004, 0]],
                },
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 11, 12, 13, 14],
                },
            }
        ],
    }
    r0 = build_graph_from_geojson(fc, 0.002, 0.0, GraphBuildOptions())
    r1 = build_graph_from_geojson(fc, 0.002, 0.0, GraphBuildOptions(remove_redundant_chain_vertices=True))
    assert r0.stats["node_count"] == 5
    assert r0.stats["edge_count"] == 4
    assert r1.stats["node_count"] == 2
    assert r1.stats["edge_count"] == 1
    pc = r1.step_metrics.get("prune_chains") or {}
    assert pc.get("vertices_removed", 0) >= 1
    only_e = next(iter(r1.graph.edges.values()))
    assert len(only_e.polyline_xy_m) == 2


def test_prune_preserves_sharp_turn():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0], [0.001, 0.001]]},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 11, 12],
                },
            }
        ],
    }
    r0 = build_graph_from_geojson(fc, 0.0005, 0.0, GraphBuildOptions())
    r1 = build_graph_from_geojson(fc, 0.0005, 0.0, GraphBuildOptions(remove_redundant_chain_vertices=True))
    assert r0.stats["node_count"] == 3
    assert r1.stats["node_count"] == 3
    assert r1.stats["edge_count"] == 2


def test_prune_preserves_gentle_arc():
    """各折れは小さいが符号が同方向に積み上がり、弦一本に潰れないこと。"""
    lon0, lat0 = 139.0, 36.0
    leg_m = 45.0
    delta = math.radians(3.5)
    n_legs = 18
    pts_xy: list[tuple[float, float]] = [(0.0, 0.0)]
    hx, hy = 1.0, 0.0
    x, y = 0.0, 0.0
    for _ in range(n_legs):
        x += hx * leg_m
        y += hy * leg_m
        pts_xy.append((x, y))
        c, s = math.cos(delta), math.sin(delta)
        hx, hy = hx * c - hy * s, hx * s + hy * c
    coords = [[lon, lat] for lon, lat in (xy_m_to_lon_lat(lon0, lat0, px, py) for px, py in pts_xy)]
    nids = list(range(5000, 5000 + len(coords)))
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": nids,
                },
            }
        ],
    }
    r0 = build_graph_from_geojson(fc, lon0, lat0, GraphBuildOptions())
    r1 = build_graph_from_geojson(fc, lon0, lat0, GraphBuildOptions(remove_redundant_chain_vertices=True))
    assert r1.stats["node_count"] < r0.stats["node_count"]
    assert r1.stats["node_count"] > 2
    assert r1.stats["edge_count"] > 1
    pc = r1.step_metrics.get("prune_chains") or {}
    assert pc.get("angle_accum_threshold_deg") == 10.0


def test_prune_chain_accum_threshold_metric_echoes_option():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0], [0.002, 0]]},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 11, 12],
                },
            }
        ],
    }
    r = build_graph_from_geojson(
        fc,
        0.002,
        0.0,
        GraphBuildOptions(
            remove_redundant_chain_vertices=True,
            prune_chain_accum_angle_deg=42.5,
        ),
    )
    pc = r.step_metrics.get("prune_chains") or {}
    assert pc.get("angle_accum_threshold_deg") == 42.5


def test_prune_signed_cancellation_collapses_zigzag():
    """符号が交互に打ち消される折れでは累積が閾値に届かず、一直線と同様に潰せること。"""
    lon0, lat0 = 139.0, 36.0
    leg_m = 35.0
    turn = math.radians(12.0)
    n_legs = 24
    pts_xy: list[tuple[float, float]] = [(0.0, 0.0)]
    hx, hy = 1.0, 0.0
    x, y = 0.0, 0.0
    sign = 1.0
    for _ in range(n_legs):
        x += hx * leg_m
        y += hy * leg_m
        pts_xy.append((x, y))
        d = sign * turn
        c, s = math.cos(d), math.sin(d)
        hx, hy = hx * c - hy * s, hx * s + hy * c
        sign *= -1.0
    coords = [[lon, lat] for lon, lat in (xy_m_to_lon_lat(lon0, lat0, px, py) for px, py in pts_xy)]
    nids = list(range(6000, 6000 + len(coords)))
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": nids,
                },
            }
        ],
    }
    r1 = build_graph_from_geojson(
        fc,
        lon0,
        lat0,
        GraphBuildOptions(
            remove_redundant_chain_vertices=True,
            prune_chain_accum_angle_deg=15.0,
        ),
    )
    assert r1.stats["node_count"] == 2
    assert r1.stats["edge_count"] == 1


def test_vertex_role_and_pile_in_geojson():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0], [0.002, 0]]},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 11, 12],
                },
            }
        ],
    }
    opts = GraphBuildOptions()
    r = build_graph_from_geojson(fc, 0.001, 0.0, opts)
    nodes_fc, _edges = graph_to_geojson_fc(r.graph, r.lon0, r.lat0, opts)
    props = [f["properties"] for f in nodes_fc["features"]]
    roles = {p["vertex_role"] for p in props}
    assert "inline" in roles
    assert "junction" in roles
    for p in props:
        assert "pile_count" in p
        assert "graph_degree" in p


def test_connect_osm_merge_metrics():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [100, 200],
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.001, 0], [0.002, 0]]},
                "properties": {
                    "osm_way_id": 2,
                    "highway": "residential",
                    "osm_node_ids": [200, 300],
                },
            },
        ],
    }
    opts = GraphBuildOptions(connect_osm_node_ids=True)
    r = build_graph_from_geojson(fc, 0.0015, 0.0, opts)
    cm = r.step_metrics.get("connect_osm") or {}
    assert cm.get("graph_vertices_removed_by_merge", 0) >= 1
    nodes_fc, _ = graph_to_geojson_fc(r.graph, r.lon0, r.lat0, opts)
    merged_highlight = [
        f["properties"].get("highlight_osm_merge")
        for f in nodes_fc["features"]
        if f["properties"].get("highlight_osm_merge")
    ]
    assert len(merged_highlight) >= 1


def test_split_intersection_one_crossing():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.0002, 0]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [1, 2]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0001, -0.0001], [0.0001, 0.0001]]},
                "properties": {"osm_way_id": 2, "highway": "residential", "osm_node_ids": [3, 4]},
            },
        ],
    }
    opts = GraphBuildOptions(split_intersections=True)
    r = build_graph_from_geojson(fc, 0.0001, 0.0, opts)
    sp = r.step_metrics.get("split") or {}
    assert sp.get("intersection_splits_applied", 0) >= 1
    assert r.stats["edge_count"] == 4
    assert r.stats["node_count"] == 5
    assert r.stats["synthetic_node_count"] == 1


def test_snap_skips_adjacent_vertices_same_edge_even_if_close():
    """隣接頂点は同一 InternalEdge の両端なので ε 内でもマージしない。"""
    dy = (1.0 / EARTH_RADIUS_M) * (180.0 / math.pi)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0, dy]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [10, 11]},
            },
        ],
    }
    opts = GraphBuildOptions(snap_endpoints=True, snap_epsilon_m=5.0)
    r = build_graph_from_geojson(fc, 0.0, 0.0, opts)
    assert r.stats["node_count"] == 2
    assert r.stats["edge_count"] == 1
    sn = r.step_metrics.get("snap") or {}
    assert sn.get("snap_clusters", 0) == 0
    assert sn.get("vertices_merged_by_snap", 0) == 0


def test_snap_skips_interior_interior_even_if_close():
    """同一 way 上でも、隣接辺でつながらない二つの中間頂点が ε 内でもマージしない。"""
    one_m = (1.0 / EARTH_RADIUS_M) * (180.0 / math.pi)
    ten_m = (10.0 / EARTH_RADIUS_M) * (180.0 / math.pi)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [0, 0],
                        [ten_m, 0],
                        [2 * ten_m, 0],
                        [ten_m + one_m, 0],
                        [3 * ten_m, 0],
                    ],
                },
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [10, 11, 12, 13, 14]},
            },
        ],
    }
    opts = GraphBuildOptions(snap_endpoints=True, snap_epsilon_m=2.0)
    r = build_graph_from_geojson(fc, 0.0, 0.0, opts)
    assert r.stats["node_count"] == 5
    sn = r.step_metrics.get("snap") or {}
    assert sn.get("snap_clusters", 0) == 0
    assert sn.get("vertices_merged_by_snap", 0) == 0


def test_snap_endpoints_merge_close_vertices():
    dy = (2.0 / EARTH_RADIUS_M) * (180.0 / math.pi)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0, 0.001]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [10, 11]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0.001 + dy], [0, 0.002]]},
                "properties": {"osm_way_id": 2, "highway": "residential", "osm_node_ids": [20, 21]},
            },
        ],
    }
    opts = GraphBuildOptions(snap_endpoints=True, snap_epsilon_m=5.0)
    r = build_graph_from_geojson(fc, 0.0, 0.0, opts)
    sn = r.step_metrics.get("snap") or {}
    assert sn.get("snap_clusters", 0) >= 1
    assert sn.get("vertices_merged_by_snap", 0) >= 1
    assert r.stats["node_count"] == 3


def test_connect_osm_two_disjoint_shared_ids():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [1, 100]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.001, 0], [0.002, 0]]},
                "properties": {"osm_way_id": 2, "highway": "residential", "osm_node_ids": [100, 2]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0.01], [0, 0.011]]},
                "properties": {"osm_way_id": 3, "highway": "residential", "osm_node_ids": [3, 200]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0.011], [0, 0.012]]},
                "properties": {"osm_way_id": 4, "highway": "residential", "osm_node_ids": [200, 4]},
            },
        ],
    }
    opts = GraphBuildOptions(connect_osm_node_ids=True)
    r = build_graph_from_geojson(fc, 0.001, 0.005, opts)
    cm = r.step_metrics.get("connect_osm") or {}
    assert cm.get("osm_id_groups_merged") == 2
    assert cm.get("graph_vertices_removed_by_merge") == 2


def test_all_graph_options_enabled_crossing_fixture():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.0002, 0]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [1, 2]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0001, -0.0001], [0.0001, 0.0001]]},
                "properties": {"osm_way_id": 2, "highway": "residential", "osm_node_ids": [3, 4]},
            },
        ],
    }
    opts = GraphBuildOptions(
        connect_osm_node_ids=True,
        split_intersections=True,
        snap_endpoints=True,
        snap_epsilon_m=5.0,
        remove_redundant_chain_vertices=True,
    )
    r = build_graph_from_geojson(fc, 0.0001, 0.0, opts)
    assert r.step_metrics.get("connect_osm") is not None
    assert (r.step_metrics.get("split") or {}).get("intersection_splits_applied", 0) >= 1
    assert r.step_metrics.get("snap") is not None
    assert r.step_metrics.get("prune_chains") is not None
    assert r.stats["node_count"] >= 1
    assert r.stats["edge_count"] >= 1


def _line_feature_from_xy(
    lon0: float,
    lat0: float,
    osm_way_id: int,
    pts: list[tuple[float, float]],
    node_start: int,
    highway: str = "residential",
) -> dict:
    coords = [[lon, lat] for lon, lat in (xy_m_to_lon_lat(lon0, lat0, x, y) for x, y in pts)]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "osm_way_id": osm_way_id,
            "highway": highway,
            "osm_node_ids": list(range(node_start, node_start + len(pts))),
        },
    }


def test_road_merge_remaps_source_junction_to_representative_anchor():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (50, 0), (100, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 5), (55, 5), (100, 5)], 200),
            _line_feature_from_xy(lon0, lat0, 3, [(55, 5), (55, 35)], 300),
        ],
    }
    opts = GraphBuildOptions(
        snap_endpoints=True,
        snap_epsilon_m=1.0,
        merge_duplicate_roads=True,
        road_merge_distance_m=8.0,
        road_merge_min_overlap_m=10.0,
        road_merge_min_overlap_ratio=0.25,
        road_merge_anchor_delta_m=1.0,
    )
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("candidate_pairs", 0) >= 1
    assert rm.get("merge_components", 0) >= 1
    assert rm.get("source_edges_removed", 0) >= 2
    assert rm.get("anchors_created", 0) >= 1

    road_merge_nodes = [n for n in r.graph.nodes.values() if not n.source_osm_node_ids]
    assert len(road_merge_nodes) >= 1
    assert any(abs(n.x_m - 55.0) < 1.0 and abs(n.y_m) < 1.0 for n in road_merge_nodes)

    side_edges = [e for e in r.graph.edges.values() if e.osm_way_id == 3]
    assert len(side_edges) == 1
    side = side_edges[0]
    assert not r.graph.nodes[side.u].source_osm_node_ids or not r.graph.nodes[side.v].source_osm_node_ids

    nodes_fc, _edges_fc = graph_to_geojson_fc(r.graph, r.lon0, r.lat0, opts)
    assert any(f["properties"].get("synthetic") for f in nodes_fc["features"])


def test_road_merge_unions_three_parallel_ways():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (100, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 4), (120, 4)], 200),
            _line_feature_from_xy(lon0, lat0, 3, [(0, 8), (140, 8)], 300),
        ],
    }
    opts = GraphBuildOptions(
        merge_duplicate_roads=True,
        road_merge_distance_m=10.0,
        road_merge_min_overlap_m=20.0,
        road_merge_min_overlap_ratio=0.25,
    )
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("candidate_pairs", 0) >= 3
    assert rm.get("union_operations", 0) >= 1
    assert rm.get("source_edges_removed", 0) >= 1


def test_road_merge_accepts_slightly_diverging_endpoint_candidate():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (80, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 8), (80, 36)], 200),
        ],
    }
    opts = _graph_opts_road_merge_for_compact_fixtures()
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("candidate_pairs", 0) >= 1
    assert rm.get("source_edges_removed", 0) >= 1


def test_road_merge_detects_segmented_parallel_ways_as_one_candidate():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (5, 0), (10, 0), (15, 0), (20, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 6), (5, 6), (10, 6), (15, 6), (20, 6)], 200),
        ],
    }
    opts = _graph_opts_road_merge_for_compact_fixtures()
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("candidate_pairs", 0) >= 1
    assert rm.get("merge_components", 0) >= 1
    assert rm.get("source_edges_removed", 0) >= 3


def test_road_merge_does_not_absorb_perpendicular_stub_way():
    """垂直の短い脇道は幹線の並列マージ成分に巻き込まれない（角度ゲート）。"""
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (100, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 5), (100, 5)], 200),
            _line_feature_from_xy(lon0, lat0, 3, [(80, 5), (80, 18)], 300),
        ],
    }
    opts = _graph_opts_road_merge_for_compact_fixtures()
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("source_edges_removed", 0) >= 1
    assert any(e.osm_way_id == 3 for e in r.graph.edges.values())
    stub = [e for e in r.graph.edges.values() if e.osm_way_id == 3]
    assert len(stub) == 1
    assert stub[0].merged_osm_way_ids == [3]


def test_road_merge_skips_merge_when_max_anchor_offset_tight():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (100, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 8), (100, 8)], 200),
        ],
    }
    opts = _graph_opts_road_merge_for_compact_fixtures(
        road_merge_distance_m=15.0,
        road_merge_max_anchor_offset_m=5.0,
    )
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("source_edges_removed", 0) == 0
    assert rm.get("skipped_merge_components", 0) >= 1


def test_road_merge_effective_max_anchor_uses_auto_when_zero():
    lon0, lat0 = 139.0, 36.0
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature_from_xy(lon0, lat0, 1, [(0, 0), (100, 0)], 100),
            _line_feature_from_xy(lon0, lat0, 2, [(0, 8), (100, 8)], 200),
        ],
    }
    r = build_graph_from_geojson(
        fc,
        lon0,
        lat0,
        _graph_opts_road_merge_for_compact_fixtures(road_merge_distance_m=15.0),
    )
    rm = r.step_metrics.get("road_merge") or {}
    assert rm.get("source_edges_removed", 0) >= 1
    assert rm.get("max_anchor_offset_m", 0) >= 50.0


def test_apply_all_graph_build_options_matches_build_graph_steps():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0], [0.002, 0]]},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": [10, 11, 12]},
            }
        ],
    }
    lon0, lat0 = 0.001, 0.0
    ways = parse_way_features(fc)

    def proj(lon: float, lat: float) -> tuple[float, float]:
        from app.osm.projection import lon_lat_to_xy_m

        return lon_lat_to_xy_m(lon0, lat0, lon, lat)

    g1 = build_native_graph(ways, proj)
    g2 = build_native_graph(ways, proj)
    opts = GraphBuildOptions(
        connect_osm_node_ids=True,
        snap_endpoints=True,
        snap_epsilon_m=2.0,
        merge_duplicate_roads=False,
        split_intersections=True,
        remove_redundant_chain_vertices=True,
    )
    m1 = apply_all_graph_build_options(g1, opts)
    r2 = build_graph_from_geojson(fc, lon0, lat0, opts)
    assert m1.keys() == r2.step_metrics.keys()
    assert len(g1.nodes) == len(r2.graph.nodes)
    assert len(g1.edges) == len(r2.graph.edges)


def test_graph_build_full_options_time_budget_on_long_chain():
    """~4k 頂点・全オプション ON で数秒以内（性能退行のガード）。"""
    lon0, lat0 = 139.0, 36.0
    n_pts = 4001
    coords = [[lon, lat] for lon, lat in (xy_m_to_lon_lat(lon0, lat0, i * 1.0, 0.0) for i in range(n_pts))]
    nids = list(range(700_000, 700_000 + n_pts))
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"osm_way_id": 1, "highway": "residential", "osm_node_ids": nids},
            }
        ],
    }
    opts = GraphBuildOptions(
        connect_osm_node_ids=True,
        snap_endpoints=True,
        snap_epsilon_m=2.0,
        merge_duplicate_roads=True,
        split_intersections=True,
        remove_redundant_chain_vertices=True,
    )
    t0 = time.perf_counter()
    r = build_graph_from_geojson(fc, lon0, lat0, opts)
    elapsed = time.perf_counter() - t0
    assert r.stats["way_input_count"] == 1
    assert r.stats["node_count"] >= 2
    assert elapsed < 20.0, f"graph build too slow: {elapsed:.2f}s, step_metrics={r.step_metrics}"
