"""Graph build metrics and node visualization metadata."""

import math

from app.osm.graph_build import GraphBuildOptions, build_graph_from_geojson, graph_to_geojson_fc
from app.osm.projection import EARTH_RADIUS_M, xy_m_to_lon_lat


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
    assert pc.get("angle_accum_threshold_deg") == 15.0


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
    r1 = build_graph_from_geojson(fc, lon0, lat0, GraphBuildOptions(remove_redundant_chain_vertices=True))
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
    assert r.stats["node_count"] == 6
    assert r.stats["synthetic_node_count"] == 2


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
