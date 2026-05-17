from dataclasses import replace
from typing import Any, Literal

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
from ..optimization.constants import (
    WEIGHT_EDGE_COUNT,
    WEIGHT_ROUTE_LENGTH,
    WEIGHT_SHAPE_DISTANCE,
    WEIGHT_SOURCE_MIRROR,
    WEIGHT_SOURCE_ROTATION,
    WEIGHT_SOURCE_SCALE,
    WEIGHT_TURN,
    WEIGHT_UNREACHABLE,
)
from ..optimization.defaults import (
    DEFAULT_ANNEAL_SEED,
    DEFAULT_COARSE_PRESOLVE,
    DEFAULT_COARSE_SCALE_BINS,
    DEFAULT_COARSE_THETA_BINS,
    DEFAULT_EVALUATION_MODE,
    DEFAULT_INCLUDE_MIRROR_STROKE,
    DEFAULT_NUM_RESTARTS,
    DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
)
from ..optimization.run import run_simulated_annealing
from ..optimization.types import AnnealOptions, OptimizeWeights, TraceStep
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


class StrokePointBody(BaseModel):
    x: float
    y: float


class OptimizeWeightsBody(BaseModel):
    source_rotation: float = WEIGHT_SOURCE_ROTATION
    source_scale: float = WEIGHT_SOURCE_SCALE
    source_mirror: float = WEIGHT_SOURCE_MIRROR
    shape_distance: float = WEIGHT_SHAPE_DISTANCE
    route_length: float = WEIGHT_ROUTE_LENGTH
    edge_count: float = WEIGHT_EDGE_COUNT
    turn: float = WEIGHT_TURN
    unreachable: float = WEIGHT_UNREACHABLE


class AnnealOptionsBody(BaseModel):
    """デバッグ UI が送る探索オプション（離散グリッド）。"""

    optimization_budget_seconds: float = Field(
        DEFAULT_OPTIMIZATION_BUDGET_SECONDS, ge=0.05, le=120.0
    )
    seed: int = DEFAULT_ANNEAL_SEED
    num_restarts: int = Field(DEFAULT_NUM_RESTARTS, ge=1, le=64)
    include_mirror_stroke: bool = DEFAULT_INCLUDE_MIRROR_STROKE
    coarse_presolve: bool = DEFAULT_COARSE_PRESOLVE
    coarse_theta_bins: int = Field(DEFAULT_COARSE_THETA_BINS, ge=2, le=64)
    coarse_scale_bins: int = Field(DEFAULT_COARSE_SCALE_BINS, ge=1, le=32)
    evaluation_mode: Literal["faithful", "elegant"] = DEFAULT_EVALUATION_MODE


def _anneal_body_to_options(body: AnnealOptionsBody | None) -> AnnealOptions:
    if body is None:
        return AnnealOptions()
    return replace(
        AnnealOptions(),
        optimization_budget_seconds=body.optimization_budget_seconds,
        seed=body.seed,
        num_restarts=body.num_restarts,
        include_mirror_stroke=body.include_mirror_stroke,
        coarse_presolve=body.coarse_presolve,
        coarse_theta_bins=body.coarse_theta_bins,
        coarse_scale_bins=body.coarse_scale_bins,
        evaluation_mode=body.evaluation_mode,
    )


class DebugOptimizeBody(BaseModel):
    """`graph-preview` と同一のグラフ入力に、キャンバス座標のストロークを足す。"""

    geojson: dict[str, Any]
    bbox: BBoxBody
    options: GraphPreprocessOptionsBody = Field(default_factory=GraphPreprocessOptionsBody)
    stroke_points: list[StrokePointBody] = Field(..., min_length=2)
    weights: OptimizeWeightsBody | None = None
    anneal: AnnealOptionsBody | None = None
    record_trace: bool = True


def _trace_step_to_dict(t: TraceStep) -> dict[str, Any]:
    return {
        "step_index": t.step_index,
        "temperature": t.temperature,
        "accepted": t.accepted,
        "score_total": t.score_total,
        "score_terms": t.score_terms,
        "transform": t.transform,
        "edge_ids": t.edge_ids,
    }


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


@router.post("/optimize")
async def debug_optimize(body: DebugOptimizeBody) -> dict[str, Any]:
    b = body.bbox
    if b.min_lat >= b.max_lat or b.min_lon >= b.max_lon:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    fc = body.geojson
    if fc.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="geojson must be a FeatureCollection")

    lon0, lat0 = bbox_center_lon_lat(b.min_lon, b.min_lat, b.max_lon, b.max_lat)
    opts = GraphPreprocessOptions(**body.options.model_dump())
    built = build_graph_from_geojson(fc, lon0, lat0, opts)

    w_body = body.weights
    weights = OptimizeWeights(**w_body.model_dump()) if w_body else OptimizeWeights()

    a_body = body.anneal
    anneal = _anneal_body_to_options(a_body)

    stroke_payload = [p.model_dump() for p in body.stroke_points]

    opt_result = run_simulated_annealing(
        built.graph,
        stroke_payload,
        lon0,
        lat0,
        weights=weights,
        opt=anneal,
        record_trace=body.record_trace,
    )

    projection_summary = (
        "表示範囲の中心を原点とした平面座標（メートル換算）でグラフを構築しました。"
    )
    steps = [_trace_step_to_dict(s) for s in opt_result.trace_steps]
    return {
        "trace_format_version": 1,
        "projection": {
            "lon0": lon0,
            "lat0": lat0,
            "mode": "local_tangent_plane",
            "summary": projection_summary,
        },
        "projection_summary": projection_summary,
        "stats": built.stats,
        "candidates_geojson": opt_result.candidates_geojson,
        "best_score": opt_result.best_score,
        "best_breakdown": opt_result.best_breakdown.as_dict(),
        "route_length_m": opt_result.best_route_length_m,
        "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
        "optimizer_meta": opt_result.optimizer_meta,
        "steps": steps,
    }
