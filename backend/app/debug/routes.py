from dataclasses import replace
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
from ..optimization.constants import (
    WEIGHT_DIJKSTRA_FALLBACK,
    WEIGHT_LOCAL_OFFSET,
    WEIGHT_OUT_OF_GRAPH,
    WEIGHT_SHAPE_DISTANCE,
    WEIGHT_SOURCE_ROTATION,
    WEIGHT_SOURCE_SCALE,
    WEIGHT_TURN,
    WEIGHT_UNREACHABLE,
)
from ..optimization.defaults import (
    DEFAULT_ANNEAL_SEED,
    DEFAULT_FINAL_TEMPERATURE,
    DEFAULT_IGNORE_OPTIMIZATION_BUDGET,
    DEFAULT_IGNORE_SOURCE_ROTATION,
    DEFAULT_INITIAL_TEMPERATURE,
    DEFAULT_LOG_SCALE_STEP,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
    DEFAULT_RESTART_COUNT,
    DEFAULT_ROTATION_STEP_RAD,
    DEFAULT_TRACE_STRIDE,
    DEFAULT_TRANSLATION_STEP_M_RATIO,
)
from ..optimization.run import run_joint_simulated_annealing, run_simulated_annealing
from ..optimization.types import AnnealOptions, OptimizeWeights, RestartResult, TraceStep, Transform
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
    shape_distance: float = WEIGHT_SHAPE_DISTANCE
    turn: float = WEIGHT_TURN
    unreachable: float = WEIGHT_UNREACHABLE
    out_of_graph: float = WEIGHT_OUT_OF_GRAPH
    dijkstra_fallback: float = WEIGHT_DIJKSTRA_FALLBACK
    local_offset: float = WEIGHT_LOCAL_OFFSET


class AnnealOptionsBody(BaseModel):
    """デバッグ UI が送る探索オプション（マルチスタート焼きなまし）。"""

    optimization_budget_seconds: float = Field(
        DEFAULT_OPTIMIZATION_BUDGET_SECONDS, ge=0.05, le=120.0
    )
    seed: int = DEFAULT_ANNEAL_SEED
    max_iterations: int = Field(DEFAULT_MAX_ITERATIONS, ge=1, le=20_000)
    restart_count: int = Field(DEFAULT_RESTART_COUNT, ge=1, le=64)
    ignore_optimization_budget: bool = DEFAULT_IGNORE_OPTIMIZATION_BUDGET
    ignore_source_rotation: bool = DEFAULT_IGNORE_SOURCE_ROTATION
    initial_temperature: float = Field(DEFAULT_INITIAL_TEMPERATURE, gt=0.0, le=10.0)
    final_temperature: float = Field(DEFAULT_FINAL_TEMPERATURE, gt=0.0, le=10.0)
    translation_step_m_ratio: float = Field(DEFAULT_TRANSLATION_STEP_M_RATIO, ge=0.0, le=2.0)
    rotation_step_rad: float = Field(DEFAULT_ROTATION_STEP_RAD, ge=0.0, le=6.28319)
    log_scale_step: float = Field(DEFAULT_LOG_SCALE_STEP, ge=0.0, le=2.0)
    trace_stride: int = Field(DEFAULT_TRACE_STRIDE, ge=1, le=10_000)


def _anneal_body_to_options(body: AnnealOptionsBody | None) -> AnnealOptions:
    if body is None:
        return AnnealOptions()
    return replace(
        AnnealOptions(),
        optimization_budget_seconds=body.optimization_budget_seconds,
        seed=body.seed,
        max_iterations=body.max_iterations,
        restart_count=body.restart_count,
        ignore_optimization_budget=body.ignore_optimization_budget,
        ignore_source_rotation=body.ignore_source_rotation,
        initial_temperature=body.initial_temperature,
        final_temperature=body.final_temperature,
        translation_step_m_ratio=body.translation_step_m_ratio,
        rotation_step_rad=body.rotation_step_rad,
        log_scale_step=body.log_scale_step,
        trace_stride=body.trace_stride,
    )


class DebugOptimizeBody(BaseModel):
    """`graph-preview` と同一のグラフ入力に、キャンバス座標のストロークを足す。"""

    geojson: dict[str, Any]
    bbox: BBoxBody
    options: GraphPreprocessOptionsBody = Field(default_factory=GraphPreprocessOptionsBody)
    # 旧フォーマット（後退互換）
    stroke_points: list[StrokePointBody] = Field(default_factory=list)
    # 新フォーマット: buildSinglePath 済みコンポーネントのリスト
    stroke_components: list[list[StrokePointBody]] | None = None
    stroke_mode: str = "single_path"
    weights: OptimizeWeightsBody | None = None
    anneal: AnnealOptionsBody | None = None
    record_trace: bool = True


def _trace_step_to_dict(t: TraceStep) -> dict[str, Any]:
    d: dict[str, Any] = {
        "step_index": t.step_index,
        "temperature": t.temperature,
        "accepted": t.accepted,
        "score_total": t.score_total,
        "score_terms": t.score_terms,
        "transform": t.transform,
        "edge_ids": t.edge_ids,
    }
    if t.edge_ids_per_component:
        d["edge_ids_per_component"] = t.edge_ids_per_component
    return d


def _transform_to_dict(t: Transform) -> dict[str, float]:
    return {
        "tx_m": t.tx_m,
        "ty_m": t.ty_m,
        "theta_rad": t.theta_rad,
        "scale": t.scale,
    }


def _restart_result_to_dict(r: RestartResult) -> dict[str, Any]:
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
        "trace_steps": [_trace_step_to_dict(s) for s in r.trace_steps],
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

    projection_summary = (
        "表示範囲の中心を原点とした平面座標（メートル換算）でグラフを構築しました。"
    )
    base_response: dict[str, Any] = {
        "trace_format_version": 2,
        "projection": {
            "lon0": lon0,
            "lat0": lat0,
            "mode": "local_tangent_plane",
            "summary": projection_summary,
        },
        "projection_summary": projection_summary,
        "stats": built.stats,
    }

    # マルチコンポーネント（ジョイント SA）パス
    if body.stroke_components is not None and len(body.stroke_components) > 1:
        components_payload = [
            [p.model_dump() for p in comp] for comp in body.stroke_components
        ]
        joint_result = run_joint_simulated_annealing(
            built.graph,
            components_payload,
            lon0,
            lat0,
            weights=weights,
            opt=anneal,
            record_trace=body.record_trace,
        )
        total_length_m = sum(c.route_length_m for c in joint_result.components)
        # best_breakdown は最初のコンポーネントを代表値として返す（デバッグ UI 互換）
        rep_bd = joint_result.components[0].best_breakdown if joint_result.components else None
        return {
            **base_response,
            "candidates_geojson": joint_result.candidates_geojson,
            "best_score": joint_result.best_joint_score,
            "best_breakdown": rep_bd.as_dict() if rep_bd else {},
            "best_restart_index": min(
                range(len(joint_result.restart_results)),
                key=lambda i: joint_result.restart_results[i].best_score,
                default=0,
            ),
            "route_length_m": total_length_m,
            "route_length_km": round(total_length_m / 1000.0, 6),
            "optimizer_meta": joint_result.optimizer_meta,
            "restarts": [_restart_result_to_dict(r) for r in joint_result.restart_results],
            "components": [
                {
                    "component_index": c.component_index,
                    "best_score": c.best_score,
                    "best_breakdown": c.best_breakdown.as_dict(),
                    "route_length_m": c.route_length_m,
                    "route_length_km": round(c.route_length_m / 1000.0, 6),
                }
                for c in joint_result.components
            ],
        }

    # シングルコンポーネントパス（既存ロジック）
    if body.stroke_components is not None and len(body.stroke_components) == 1:
        stroke_payload = [p.model_dump() for p in body.stroke_components[0]]
    elif body.stroke_points:
        stroke_payload = [p.model_dump() for p in body.stroke_points]
    else:
        raise HTTPException(status_code=400, detail="stroke_components or stroke_points is required")

    opt_result = run_simulated_annealing(
        built.graph,
        stroke_payload,
        lon0,
        lat0,
        weights=weights,
        opt=anneal,
        record_trace=body.record_trace,
    )

    return {
        **base_response,
        "candidates_geojson": opt_result.candidates_geojson,
        "best_score": opt_result.best_score,
        "best_breakdown": opt_result.best_breakdown.as_dict(),
        "best_restart_index": opt_result.best_restart_index,
        "route_length_m": opt_result.best_route_length_m,
        "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
        "optimizer_meta": opt_result.optimizer_meta,
        "restarts": [_restart_result_to_dict(r) for r in opt_result.restart_results],
        "components": [
            {
                "component_index": 0,
                "best_score": opt_result.best_score,
                "best_breakdown": opt_result.best_breakdown.as_dict(),
                "route_length_m": opt_result.best_route_length_m,
                "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
            }
        ],
    }
