from typing import Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..osm.geojson import overpass_elements_to_geojson
from ..osm.graph_build import (
    DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
    GraphBuildOptions,
    build_graph_from_geojson,
    graph_to_geojson_fc,
)
from ..osm.projection import bbox_center_lon_lat
from ..overpass.client import fetch_interpreter
from .preview import ways_raw_preview
from .road_type_allowlist import DEBUG_ROAD_TYPE_ALLOWLIST

router = APIRouter()


class BBoxBody(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


class GraphBuildOptionsBody(BaseModel):
    connect_osm_node_ids: bool = False
    snap_endpoints: bool = False
    snap_epsilon_m: float = Field(3.0, ge=0.05, le=500.0)
    split_intersections: bool = False
    remove_redundant_chain_vertices: bool = False
    prune_chain_accum_angle_deg: float = Field(
        DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
        ge=0.5,
        le=179.0,
        description="チェーン簡略化で累積折れ角の絶対値がこの度以上の頂点を残す",
    )


class GraphPreviewBody(BaseModel):
    geojson: dict[str, Any]
    bbox: BBoxBody
    options: GraphBuildOptionsBody = Field(default_factory=GraphBuildOptionsBody)


@router.get("/ways")
async def debug_ways(
    road_type: Annotated[
        list[str],
        Query(
            min_length=1,
            description="含める道路種別（OSM の highway=* の値）",
        ),
    ],
    min_lat: float = Query(..., description="South edge (WGS84)"),
    min_lon: float = Query(..., description="West edge"),
    max_lat: float = Query(..., description="North edge"),
    max_lon: float = Query(..., description="East edge"),
    limit: int = Query(1000, ge=1, le=2000),
) -> dict[str, Any]:
    if min_lat >= max_lat or min_lon >= max_lon:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    selected: list[str] = []
    seen: set[str] = set()
    for rt in road_type:
        if rt not in DEBUG_ROAD_TYPE_ALLOWLIST:
            raise HTTPException(
                status_code=400,
                detail=f"許可されていない道路種別です: {rt!r}",
            )
        if rt not in seen:
            seen.add(rt)
            selected.append(rt)

    # south,west,north,east — way を bbox で絞り、ノード参照を取得して頂点ごとの OSM node id を復元する
    way_lines = "\n".join(
        f'  way["highway"="{h}"]({min_lat},{min_lon},{max_lat},{max_lon});'
        for h in selected
    )
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
    geojson = overpass_elements_to_geojson(elements, limit_ways=limit)
    raw_preview = ways_raw_preview(ways_sorted[:limit])

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
    opts = GraphBuildOptions(**body.options.model_dump())
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
