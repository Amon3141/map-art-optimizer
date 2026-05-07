import json
import os
from typing import Annotated, Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# デバッグ /api/debug/highways で許可する highway=* の値（Overpass にそのまま渡す）
DEBUG_HIGHWAY_WHITELIST: frozenset[str] = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
    }
)
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app = FastAPI(title="地図アート作成機 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ways_to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        coords: list[list[float]] = []
        for node in geom:
            lat = node.get("lat")
            lon = node.get("lon")
            if lat is None or lon is None:
                continue
            coords.append([float(lon), float(lat)])
        if len(coords) < 2:
            continue
        tags = dict(el.get("tags") or {})
        way_id = el.get("id")
        # OSM に rare だが id=* タグがあると "id" がタグで上書きされ、一覧・強調のキーがずれる。
        # osm_way_id は必ずタグの後に置き、way の要素 id を固定する。
        properties = {**tags, "osm_way_id": way_id}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def way_element_for_preview(el: dict[str, Any]) -> dict[str, Any]:
    """テキストプレビュー用: タグ等はそのまま、nodes / geometry は件数のみ。"""
    nodes = el.get("nodes")
    geometry = el.get("geometry")
    preview = {k: v for k, v in el.items() if k not in ("nodes", "geometry")}
    preview["nodes_count"] = len(nodes) if isinstance(nodes, list) else 0
    preview["geometry_count"] = len(geometry) if isinstance(geometry, list) else 0
    return preview


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/debug/highways")
async def debug_highways(
    highway: Annotated[
        list[str],
        Query(
            min_length=1,
            description="含める highway=*",
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
    for h in highway:
        if h not in DEBUG_HIGHWAY_WHITELIST:
            raise HTTPException(
                status_code=400,
                detail=f"許可されていない highway 値です: {h!r}",
            )
        if h not in seen:
            seen.add(h)
            selected.append(h)

    # south,west,north,east — クエリ全体を表示範囲（bbox）に制限
    way_lines = "\n".join(f'  way["highway"="{h}"];' for h in selected)
    query = f"""[bbox:{min_lat},{min_lon},{max_lat},{max_lon}][out:json][timeout:25];
(
{way_lines}
);
out geom;
"""
    headers = {
        "User-Agent": "map-draw-optimizer/0.1 (local dev; contact: local)",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(OVERPASS_URL, content=query.encode(), headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Overpass error: {e}") from e

    elements = data.get("elements") or []
    ways = [e for e in elements if e.get("type") == "way"][:limit]
    geojson = ways_to_geojson(ways)

    preview_obj: dict[str, Any] = {
        "elements": [way_element_for_preview(w) for w in ways],
    }
    raw_preview = json.dumps(preview_obj, ensure_ascii=False, indent=2)
    if len(raw_preview) > 12000:
        raw_preview = raw_preview[:12000] + "\n… (truncated)"

    return {"geojson": geojson, "raw_preview": raw_preview, "count": len(ways)}
