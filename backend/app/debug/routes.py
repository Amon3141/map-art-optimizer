from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..osm.geojson import overpass_elements_to_geojson
from ..osm.ingest import build_graph_from_geojson, graph_to_geojson_fc
from ..osm.overpass import fetch_interpreter
from ..osm.projection import bbox_center_lon_lat
from ..preprocess import (
    DEFAULT_CONNECT_OSM_NODE_IDS_ENABLED,
    DEFAULT_MERGE_DUPLICATE_ROADS_ENABLED,
    DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
    DEFAULT_REMOVE_REDUNDANT_CHAIN_VERTICES_ENABLED,
    DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
    DEFAULT_ROAD_MERGE_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_DISTANCE_M,
    DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
    DEFAULT_SNAP_ENDPOINTS_ENABLED,
    DEFAULT_SNAP_EPSILON_M,
    DEFAULT_SPLIT_INTERSECTIONS_ENABLED,
    GraphPreprocessOptions,
)
from .preview import ways_raw_preview

router = APIRouter()

# Overpass 応答の way 件数の上限（メモリ・応答サイズの安全弁。通常は bbox を絞れば十分小さい）
DEBUG_OVERPASS_MAX_WAYS = 250_000


class BBoxBody(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


class GraphPreprocessOptionsBody(BaseModel):
    connect_osm_node_ids_enabled: bool = DEFAULT_CONNECT_OSM_NODE_IDS_ENABLED
    snap_endpoints_enabled: bool = DEFAULT_SNAP_ENDPOINTS_ENABLED
    snap_epsilon_m: float = Field(DEFAULT_SNAP_EPSILON_M, ge=0.05, le=500.0)
    merge_duplicate_roads_enabled: bool = DEFAULT_MERGE_DUPLICATE_ROADS_ENABLED
    road_merge_distance_m: float = Field(DEFAULT_ROAD_MERGE_DISTANCE_M, ge=0.5, le=100.0)
    road_merge_angle_deg: float = Field(DEFAULT_ROAD_MERGE_ANGLE_DEG, ge=0.5, le=45.0)
    road_merge_min_overlap_m: float = Field(DEFAULT_ROAD_MERGE_MIN_OVERLAP_M, ge=0.0, le=500.0)
    road_merge_min_overlap_ratio: float = Field(DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO, ge=0.0, le=1.0)
    road_merge_anchor_delta_m: float = Field(DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M, ge=0.05, le=50.0)
    road_merge_max_anchor_offset_m: float = Field(DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M, ge=0.0, le=500.0)
    split_intersections_enabled: bool = DEFAULT_SPLIT_INTERSECTIONS_ENABLED
    remove_redundant_chain_vertices_enabled: bool = DEFAULT_REMOVE_REDUNDANT_CHAIN_VERTICES_ENABLED
    prune_chain_accum_angle_deg: float = Field(
        DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
        ge=0.5,
        le=179.0,
        description="チェーン簡略化で累積折れ角の絶対値がこの度以上の頂点を残す",
    )


class GraphPreviewBody(BaseModel):
    geojson: dict[str, Any]
    bbox: BBoxBody
    options: GraphPreprocessOptionsBody = Field(default_factory=GraphPreprocessOptionsBody)


@router.get("/ways")
async def debug_ways(
    min_lat: float = Query(..., description="South edge (WGS84)"),
    min_lon: float = Query(..., description="West edge"),
    max_lat: float = Query(..., description="North edge"),
    max_lon: float = Query(..., description="East edge"),
) -> dict[str, Any]:
    if min_lat >= max_lat or min_lon >= max_lon:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    # south,west,north,east — bbox 内の highway タグ付き way をすべて（クライアント側で種別フィルタ）
    way_lines = f'  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});'
    query = f"""[out:json][timeout:25];
(
{way_lines}
);
out body;
>;
out skel qt;
"""
    try:
        data = await fetch_interpreter(query)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Overpass error: {e}") from e

    elements = data.get("elements") or []
    ways = [e for e in elements if e.get("type") == "way"]
    ways_sorted = sorted(ways, key=lambda w: int(w.get("id") or 0))
    if len(ways_sorted) > DEBUG_OVERPASS_MAX_WAYS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"この範囲の way が多すぎます（{len(ways_sorted)} 件、上限 {DEBUG_OVERPASS_MAX_WAYS}）。"
                " 地図をズームして範囲を狭くしてください。"
            ),
        )
    geojson = overpass_elements_to_geojson(elements, limit_ways=None)
    raw_preview = ways_raw_preview(ways_sorted)

    return {"geojson": geojson, "raw_preview": raw_preview, "count": len(geojson.get("features") or [])}


@router.post("/graph-preview")
async def debug_graph_preview(body: GraphPreviewBody) -> dict[str, Any]:
    b = body.bbox
    if b.min_lat >= b.max_lat or b.min_lon >= b.max_lon:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    fc = body.geojson
    if fc.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="geojson must be a FeatureCollection")

    lon0, lat0 = bbox_center_lon_lat(b.min_lon, b.min_lat, b.max_lon, b.max_lat)
    opts = GraphPreprocessOptions(**body.options.model_dump())
    result = build_graph_from_geojson(fc, lon0, lat0, opts)
    nodes_fc, edges_fc = graph_to_geojson_fc(result.graph, lon0, lat0, opts)
    projection_summary = (
        "表示範囲の中心を原点とした平面座標（メートル換算）でグラフを構築しました。"
    )
    return {
        "projection": {
            "lon0": lon0,
            "lat0": lat0,
            "mode": "local_tangent_plane",
            "summary": projection_summary,
        },
        "projection_summary": projection_summary,
        "stats": result.stats,
        "step_metrics": result.step_metrics,
        "graph_geojson": {
            "nodes": nodes_fc,
            "edges": edges_fc,
        },
    }
