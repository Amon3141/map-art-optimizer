from typing import Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..osm.geojson import ways_to_geojson
from ..overpass.client import fetch_interpreter
from .preview import ways_raw_preview
from .road_type_allowlist import DEBUG_ROAD_TYPE_ALLOWLIST

router = APIRouter()


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
    limit: int = Query(100, ge=1, le=500),
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

    # south,west,north,east — クエリ全体を表示範囲（bbox）に制限
    way_lines = "\n".join(f'  way["highway"="{h}"];' for h in selected)
    query = f"""[bbox:{min_lat},{min_lon},{max_lat},{max_lon}][out:json][timeout:25];
(
{way_lines}
);
out geom;
"""
    try:
        data = await fetch_interpreter(query)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Overpass error: {e}") from e

    elements = data.get("elements") or []
    ways = [e for e in elements if e.get("type") == "way"][:limit]
    geojson = ways_to_geojson(ways)
    raw_preview = ways_raw_preview(ways)

    return {"geojson": geojson, "raw_preview": raw_preview, "count": len(ways)}
