"""
本番アプリ用最適化エンドポイント。

デバッグエンドポイント（/api/debug/*）とは異なり、道路データ取得・グラフ構築・
最適化を一括で内部実施する。ユーザーが直接 OSM データや前処理を操作しない。
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .osm.geojson import overpass_elements_to_geojson
from .osm.ingest import build_graph_from_geojson, graph_to_geojson_fc
from .osm.overpass import fetch_interpreter
from .preprocess import GraphPreprocessOptions
from .optimization.production_defaults import (
    ADAPTIVE_RADIUS_MIN_M,
    MAX_WAY_BUDGET_ADAPTIVE,
    PILOT_FALLBACK_DENSITY,
    PILOT_QUERY_RADIUS_M,
    PRODUCTION_IGNORE_SOURCE_ROTATION,
    PRODUCTION_OVERPASS_MAX_WAYS,
    SPEED_PRESETS,
    SpeedPreset,
    SpeedPresetConfig,
)
from .optimization.run import run_joint_simulated_annealing, run_simulated_annealing
from .optimization.serialize import restart_result_to_dict
from .optimization.types import AnnealOptions, OptimizeWeights

router = APIRouter()


class StrokePointBody(BaseModel):
    x: float
    y: float


class ProductionOptimizeBody(BaseModel):
    stroke_components: list[list[StrokePointBody]]
    center_lon: float = Field(..., ge=-180.0, le=180.0)
    center_lat: float = Field(..., ge=-90.0, le=90.0)
    speed_preset: SpeedPreset = "normal"
    ignore_source_rotation: bool = PRODUCTION_IGNORE_SOURCE_ROTATION


def _center_to_bbox(
    lon: float, lat: float, radius_m: float
) -> tuple[float, float, float, float]:
    """中心座標 + 半径 → (min_lat, min_lon, max_lat, max_lon)"""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


async def _estimate_way_density_per_km2(lon: float, lat: float) -> float:
    """半径 300m の bbox で highway way 数をカウントし、密度 (ways/km²) を返す。
    失敗時は PILOT_FALLBACK_DENSITY を返す（処理を止めない）。"""
    r = float(PILOT_QUERY_RADIUS_M)
    min_lat, min_lon, max_lat, max_lon = _center_to_bbox(lon, lat, r)
    query = f"""[out:json][timeout:6];
way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
out count;
"""
    try:
        data = await fetch_interpreter(query, timeout_s=8.0)
        elements = data.get("elements") or []
        way_count = int(elements[0]["tags"]["ways"]) if elements else 0
        area_km2 = math.pi * (r / 1000.0) ** 2
        return way_count / area_km2 if area_km2 > 0 else PILOT_FALLBACK_DENSITY
    except Exception:
        return PILOT_FALLBACK_DENSITY


def _compute_adaptive_radius(way_density: float, preset: SpeedPresetConfig) -> float:
    """道路密度から way 数予算内に収まる最大半径を返す。preset.fetch_radius_m が上限。"""
    area_km2 = MAX_WAY_BUDGET_ADAPTIVE / max(way_density, 1.0)
    radius_m = math.sqrt(area_km2 / math.pi) * 1000.0
    return max(ADAPTIVE_RADIUS_MIN_M, min(radius_m, preset.fetch_radius_m))


@router.post("/optimize")
async def production_optimize(body: ProductionOptimizeBody) -> dict[str, Any]:
    if len(body.stroke_components) < 1:
        raise HTTPException(status_code=400, detail="stroke_components must be non-empty")

    preset = SPEED_PRESETS[body.speed_preset]

    # パイロットクエリで道路密度を推定し、適応半径を決定（失敗時はフォールバック）
    way_density = await _estimate_way_density_per_km2(body.center_lon, body.center_lat)
    radius_m = _compute_adaptive_radius(way_density, preset)
    min_lat, min_lon, max_lat, max_lon = _center_to_bbox(
        body.center_lon, body.center_lat, radius_m
    )

    # --- 道路データ取得 ---
    way_query = f"""[out:json][timeout:30];
(
  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
>;
out skel qt;
"""
    try:
        data = await fetch_interpreter(way_query, timeout_s=40.0)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"道路データの取得に失敗しました: {e}") from e

    elements = data.get("elements") or []
    ways = [e for e in elements if e.get("type") == "way"]
    if len(ways) > PRODUCTION_OVERPASS_MAX_WAYS:
        raise HTTPException(
            status_code=413,
            detail="この場所は道路データが多すぎて処理できませんでした。別のエリアを試してみてください。",
        )

    fc = overpass_elements_to_geojson(elements, limit_ways=None)

    # --- グラフ構築 ---
    lon0, lat0 = body.center_lon, body.center_lat
    opts = GraphPreprocessOptions()
    built = build_graph_from_geojson(fc, lon0, lat0, opts)

    # トレース再生用のエッジ GeoJSON
    _nodes_fc, edges_fc = graph_to_geojson_fc(built.graph, lon0, lat0, opts)

    # --- 最適化オプション ---
    anneal = replace(
        AnnealOptions(),
        optimization_budget_seconds=preset.budget_s,
        restart_count=preset.restart_count,
        max_iterations=preset.max_iterations,
        ignore_source_rotation=body.ignore_source_rotation,
    )
    weights = OptimizeWeights()

    projection_info = {
        "lon0": lon0,
        "lat0": lat0,
        "mode": "local_tangent_plane",
    }

    # --- 最適化実行 ---
    if len(body.stroke_components) > 1:
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
            record_trace=True,
        )
        total_length_m = sum(c.route_length_m for c in joint_result.components)
        rep_bd = joint_result.components[0].best_breakdown if joint_result.components else None
        return {
            "projection": projection_info,
            "candidates_geojson": joint_result.candidates_geojson,
            "ranked_candidates": joint_result.ranked_candidates,
            "best_score": joint_result.best_joint_score,
            "best_breakdown": rep_bd.as_dict() if rep_bd else {},
            "best_restart_index": min(
                range(len(joint_result.restart_results)),
                key=lambda i: joint_result.restart_results[i].best_score,
                default=0,
            ),
            "route_length_m": total_length_m,
            "route_length_km": round(total_length_m / 1000.0, 6),
            "restarts": [restart_result_to_dict(r) for r in joint_result.restart_results],
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
            "edges_geojson": edges_fc,
        }

    stroke_payload = [p.model_dump() for p in body.stroke_components[0]]
    opt_result = run_simulated_annealing(
        built.graph,
        stroke_payload,
        lon0,
        lat0,
        weights=weights,
        opt=anneal,
        record_trace=True,
    )
    return {
        "projection": projection_info,
        "candidates_geojson": opt_result.candidates_geojson,
        "ranked_candidates": opt_result.ranked_candidates,
        "best_score": opt_result.best_score,
        "best_breakdown": opt_result.best_breakdown.as_dict(),
        "best_restart_index": opt_result.best_restart_index,
        "route_length_m": opt_result.best_route_length_m,
        "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
        "restarts": [restart_result_to_dict(r) for r in opt_result.restart_results],
        "components": [
            {
                "component_index": 0,
                "best_score": opt_result.best_score,
                "best_breakdown": opt_result.best_breakdown.as_dict(),
                "route_length_m": opt_result.best_route_length_m,
                "route_length_km": round(opt_result.best_route_length_m / 1000.0, 6),
            }
        ],
        "edges_geojson": edges_fc,
    }
