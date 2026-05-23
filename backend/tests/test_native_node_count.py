"""ネイティブノード数カウントと本番ノード上限。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.optimization.app_defaults import MAX_NATIVE_GRAPH_NODES
from app.osm.ingest import count_native_nodes_from_geojson
def _line_feature(way_id: int, n_coords: int) -> dict:
    coords = [[float(i), 0.0] for i in range(n_coords)]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "osm_way_id": way_id,
            "osm_node_ids": list(range(n_coords)),
            "highway": "residential",
        },
    }


def test_count_native_nodes_from_geojson_sums_coordinates() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature(1, 3),
            _line_feature(2, 5),
        ],
    }
    assert count_native_nodes_from_geojson(fc) == 8


def test_count_native_nodes_skips_invalid_features() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            _line_feature(1, 4),
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {},
            },
        ],
    }
    assert count_native_nodes_from_geojson(fc) == 4


def _optimize_body() -> dict:
    return {
        "stroke_components": [
            [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}],
        ],
        "center_lon": 139.7671,
        "center_lat": 35.6812,
        "speed_preset": "fast",
        "fetch_radius_m": 3000,
    }


def test_optimize_rejects_graph_too_many_nodes() -> None:
    over_fc = {
        "type": "FeatureCollection",
        "features": [_line_feature(1, MAX_NATIVE_GRAPH_NODES + 1)],
    }
    client = TestClient(app)
    with patch(
        "app.routes.fetch_highway_geojson_for_center",
        new_callable=AsyncMock,
        return_value=over_fc,
    ):
        res = client.post("/api/optimize", json=_optimize_body())

    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "graph_too_many_nodes"
    assert str(MAX_NATIVE_GRAPH_NODES + 1) in detail["message"]


def test_node_limit_boundary_counts() -> None:
    at_limit_fc = {
        "type": "FeatureCollection",
        "features": [_line_feature(1, MAX_NATIVE_GRAPH_NODES)],
    }
    over_fc = {
        "type": "FeatureCollection",
        "features": [_line_feature(1, MAX_NATIVE_GRAPH_NODES + 1)],
    }
    assert count_native_nodes_from_geojson(at_limit_fc) == MAX_NATIVE_GRAPH_NODES
    assert count_native_nodes_from_geojson(over_fc) > MAX_NATIVE_GRAPH_NODES
