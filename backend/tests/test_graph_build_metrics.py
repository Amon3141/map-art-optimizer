"""Graph build metrics and node visualization metadata."""

import math

from app.osm.graph_build import GraphBuildOptions, build_graph_from_geojson, graph_to_geojson_fc
from app.osm.projection import EARTH_RADIUS_M


def test_step_metrics_deduplicate_only():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0, 0], [0.002, 0]]},
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 10, 11],
                },
            }
        ],
    }
    opts = GraphBuildOptions(deduplicate_geometry=True)
    r = build_graph_from_geojson(fc, 0.001, 0.0, opts)
    assert r.step_metrics.get("deduplicate") is not None
    dd = r.step_metrics["deduplicate"]
    assert dd["way_vertices_before"] == 3
    assert dd["way_vertices_after"] == 2
    assert dd["removed_duplicate_vertices"] == 1
    rm_e = r.dedupe_removed_edges_geojson["features"]
    rm_v = r.dedupe_removed_vertices_geojson["features"]
    assert len(rm_v) == 1
    assert rm_v[0]["geometry"]["type"] == "Point"


def test_dedupe_removed_geometry_overlay_dup_nid_non_degenerate_segment():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 0], [0.001, 0], [0.002, 0]],
                },
                "properties": {
                    "osm_way_id": 1,
                    "highway": "residential",
                    "osm_node_ids": [10, 10, 11],
                },
            }
        ],
    }
    opts = GraphBuildOptions(deduplicate_geometry=True)
    r = build_graph_from_geojson(fc, 0.001, 0.0, opts)
    rm_e = r.dedupe_removed_edges_geojson["features"]
    rm_v = r.dedupe_removed_vertices_geojson["features"]
    assert len(rm_v) == 1
    assert len(rm_e) == 1
    assert rm_e[0]["geometry"]["type"] == "LineString"


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
    )
    r = build_graph_from_geojson(fc, 0.0001, 0.0, opts)
    assert r.step_metrics.get("connect_osm") is not None
    assert (r.step_metrics.get("split") or {}).get("intersection_splits_applied", 0) >= 1
    assert r.step_metrics.get("snap") is not None
    assert r.stats["node_count"] >= 1
    assert r.stats["edge_count"] >= 1
