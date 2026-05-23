"""Overpass API（/api/interpreter）への非同期 HTTP クライアントと highway way 取得。"""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Sequence
from math import ceil
from typing import Any

import httpx

from .geojson import overpass_elements_to_geojson
from .highway_include import INCLUDED_HIGHWAY_TYPES

# center_lon/lat を ~1km グリッドに丸め、fetch_radius_m を 500m 切り上げしたキーで
# Overpass レスポンスをキャッシュする。同一エリアの重複呼び出しを防ぐ。
_CACHE_TTL_S = 300.0
_cache: dict[tuple[float, float, float], tuple[float, dict[str, Any]]] = {}


def _cache_key(center_lon: float, center_lat: float, fetch_radius_m: float) -> tuple[float, float, float]:
    return (
        round(center_lon, 2),
        round(center_lat, 2),
        float(500 * ceil(fetch_radius_m / 500)),
    )

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

_DEFAULT_HEADERS = {
    "User-Agent": "map-art-optimizer/1.0 (contact: amon.kizawa@icloud.com)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def center_radius_to_bbox(
    lon: float, lat: float, radius_m: float
) -> tuple[float, float, float, float]:
    """中心座標 + 半径 → (min_lat, min_lon, max_lat, max_lon)。"""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def highway_bbox_query(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    query_timeout_s: int = 25,
    highway_values: Sequence[str] | None = None,
) -> str:
    """bbox 内の highway タグ付き way を取得する Overpass QL。

    highway_values が None のときは way[\"highway\"] 全件。指定時はその値のみ（regex フィルタ）。
    """
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    if highway_values is None:
        way_line = f'  way["highway"]({bbox});'
    else:
        pattern = "|".join(re.escape(v) for v in highway_values)
        way_line = f'  way["highway"~"^({pattern})$"]({bbox});'
    return f"""[out:json][timeout:{query_timeout_s}];
(
{way_line}
);
out body;
>;
out skel qt;
"""


async def fetch_interpreter(query: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(OVERPASS_URL, content=query.encode(), headers=_DEFAULT_HEADERS)
        r.raise_for_status()
        return r.json()


async def fetch_highway_elements_for_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    timeout_s: float = 60.0,
    query_timeout_s: int = 25,
    highway_values: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """bbox 内の highway way 要素列を返す。"""
    query = highway_bbox_query(
        min_lat,
        min_lon,
        max_lat,
        max_lon,
        query_timeout_s=query_timeout_s,
        highway_values=highway_values,
    )
    data = await fetch_interpreter(query, timeout_s=timeout_s)
    return data.get("elements") or []


async def fetch_highway_geojson_for_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    max_ways: int,
    timeout_s: float = 60.0,
    query_timeout_s: int = 25,
) -> dict[str, Any]:
    elements = await fetch_highway_elements_for_bbox(
        min_lat,
        min_lon,
        max_lat,
        max_lon,
        timeout_s=timeout_s,
        query_timeout_s=query_timeout_s,
        highway_values=INCLUDED_HIGHWAY_TYPES,
    )
    return overpass_elements_to_geojson(elements, limit_ways=max_ways)


async def fetch_highway_geojson_for_center(
    center_lon: float,
    center_lat: float,
    fetch_radius_m: float,
    *,
    max_ways: int,
    timeout_s: float = 20.0,
    query_timeout_s: int = 30,
) -> dict[str, Any]:
    key = _cache_key(center_lon, center_lat, fetch_radius_m)
    cached = _cache.get(key)
    if cached is not None:
        expires_at, data = cached
        if time.monotonic() < expires_at:
            return data

    # キャッシュキーの丸めた値でリクエスト（少し広い bbox → 問題なし）
    rounded_lon, rounded_lat, rounded_radius = key
    min_lat, min_lon, max_lat, max_lon = center_radius_to_bbox(
        rounded_lon, rounded_lat, rounded_radius
    )
    data = await fetch_highway_geojson_for_bbox(
        min_lat,
        min_lon,
        max_lat,
        max_lon,
        max_ways=max_ways,
        timeout_s=timeout_s,
        query_timeout_s=query_timeout_s,
    )
    _cache[key] = (time.monotonic() + _CACHE_TTL_S, data)
    return data
