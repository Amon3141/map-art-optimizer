"""
本番アプリ用最適化エンドポイント。

道路データ取得・グラフ構築・最適化を一括で内部実施する。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .osm.ingest import build_graph_from_geojson, count_native_nodes_from_geojson, graph_to_geojson_fc
from .osm.overpass import fetch_highway_geojson_for_center
from .preprocess import GraphPreprocessOptions
from .preprocess.defaults import OVERPASS_MAX_WAYS
from .optimization.app_defaults import (
    DEFAULT_FETCH_RADIUS_M,
    DEFAULT_SPEED_PRESET,
    FETCH_RADIUS_MAX_M,
    FETCH_RADIUS_MIN_M,
    IGNORE_SOURCE_ROTATION_DEFAULT,
    MAX_NATIVE_GRAPH_NODES,
    SPEED_PRESETS,
    SpeedPreset,
)
from .optimization.pipeline import run_optimization_pipeline
from .optimization.types import AnnealOptions, OptimizeWeights
from ._limiter import limiter

router = APIRouter()


class StrokePointBody(BaseModel):
    x: float
    y: float


class OptimizeBody(BaseModel):
    stroke_components: Annotated[
        list[Annotated[list[StrokePointBody], Field(max_length=500)]],
        Field(max_length=10),
    ]
    center_lon: float = Field(..., ge=-180.0, le=180.0)
    center_lat: float = Field(..., ge=-90.0, le=90.0)
    speed_preset: SpeedPreset = DEFAULT_SPEED_PRESET
    fetch_radius_m: float = Field(
        default=DEFAULT_FETCH_RADIUS_M,
        ge=FETCH_RADIUS_MIN_M,
        le=FETCH_RADIUS_MAX_M,
    )
    ignore_source_rotation: bool = IGNORE_SOURCE_ROTATION_DEFAULT


@router.post("/optimize")
@limiter.limit("10/minute")
async def optimize(body: OptimizeBody, request: Request) -> dict[str, Any]:
    # 速度プリセットと投影原点を決める
    preset = SPEED_PRESETS[body.speed_preset]
    lon0, lat0 = body.center_lon, body.center_lat

    # OSM 道路データを取得する
    try:
        fc = await fetch_highway_geojson_for_center(
            lon0,
            lat0,
            body.fetch_radius_m,
            max_ways=OVERPASS_MAX_WAYS,
            timeout_s=20.0,
            query_timeout_s=30,
        )
    except httpx.TimeoutException as e:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "osm_fetch_timeout",
                "message": "道路データの取得に時間がかかりすぎました。時間をおいて再試行してください。",
            },
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "osm_fetch_failed",
                "message": "道路データの取得に失敗しました。時間をおいて再試行してください。",
            },
        ) from e

    native_node_count = count_native_nodes_from_geojson(fc)
    if native_node_count > MAX_NATIVE_GRAPH_NODES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "graph_too_many_nodes",
                "message": (
                    f"道路データの規模が大きすぎます（ノード {native_node_count} 個）。"
                    "探索範囲を小さくして再試行してください。"
                ),
            },
        )

    # 道路グラフを構築する
    opts = GraphPreprocessOptions()
    built = build_graph_from_geojson(fc, lon0, lat0, opts)
    _nodes_fc, edges_fc = graph_to_geojson_fc(built.graph, lon0, lat0, opts)

    # 焼きなまし探索パラメータを組み立てる
    anneal = replace(
        AnnealOptions(),
        optimization_budget_seconds=preset.budget_s,
        restart_count=preset.restart_count,
        max_iterations=preset.max_iterations,
        ignore_source_rotation=body.ignore_source_rotation,
    )
    components_payload = [
        [p.model_dump() for p in comp] for comp in body.stroke_components
    ]

    # 焼きなましを実行する
    try:
        result = run_optimization_pipeline(
            built.graph,
            lon0,
            lat0,
            components_payload,
            weights=OptimizeWeights(),
            anneal=anneal,
            record_trace=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 最適化結果を返す
    return {
        "projection": {
            "lon0": lon0,
            "lat0": lat0,
            "mode": "local_tangent_plane",
        },
        **result,
        "edges_geojson": edges_fc,
    }
