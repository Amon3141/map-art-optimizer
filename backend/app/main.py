import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
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
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"id": el.get("id"), **{k: v for k, v in el.get("tags", {}).items()}},
            }
        )
    return {"type": "FeatureCollection", "features": features}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/debug/highways")
async def debug_highways(
    min_lat: float = Query(..., description="South edge (WGS84)"),
    min_lon: float = Query(..., description="West edge"),
    max_lat: float = Query(..., description="North edge"),
    max_lon: float = Query(..., description="East edge"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    if min_lat >= max_lat or min_lon >= max_lon:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    query = f"""
[out:json][timeout:25];
(
  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
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

    preview_obj: dict[str, Any] = {"elements": ways}
    raw_preview = json.dumps(preview_obj, ensure_ascii=False, indent=2)
    if len(raw_preview) > 12000:
        raw_preview = raw_preview[:12000] + "\n… (truncated)"

    return {"geojson": geojson, "raw_preview": raw_preview, "count": len(ways)}
