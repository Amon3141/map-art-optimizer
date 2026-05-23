"""Overpass API（/api/interpreter）への非同期 HTTP クライアントと highway way 取得。"""

from __future__ import annotations

import math
import os
from typing import Any

import httpx

from .geojson import overpass_elements_to_geojson

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

_DEFAULT_HEADERS = {
    "User-Agent": "map-draw-optimizer/0.1 (local dev; contact: local)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


class OverpassTooManyWaysError(Exception):
    """Overpass 応答の way 件数が上限を超えた。"""

    def __init__(self, way_count: int, max_ways: int) -> None:
        self.way_count = way_count
        self.max_ways = max_ways
        super().__init__(f"way count {way_count} exceeds limit {max_ways}")


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
) -> str:
    """bbox 内の highway タグ付き way を取得する Overpass QL。"""
    way_lines = f'  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});'
    return f"""[out:json][timeout:{query_timeout_s}];
(
{way_lines}
);
out body;
>;
out skel qt;
"""


def _ways_from_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in elements if e.get("type") == "way"]


def _check_way_count(ways: list[dict[str, Any]], max_ways: int) -> None:
    if len(ways) > max_ways:
        raise OverpassTooManyWaysError(len(ways), max_ways)


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
    max_ways: int,
    timeout_s: float = 60.0,
    query_timeout_s: int = 25,
) -> list[dict[str, Any]]:
    """bbox 内の highway way 要素列を返す。way 件数が max_ways を超えると OverpassTooManyWaysError。"""
    query = highway_bbox_query(
        min_lat, min_lon, max_lat, max_lon, query_timeout_s=query_timeout_s
    )
    data = await fetch_interpreter(query, timeout_s=timeout_s)
    elements = data.get("elements") or []
    _check_way_count(_ways_from_elements(elements), max_ways)
    return elements


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
        max_ways=max_ways,
        timeout_s=timeout_s,
        query_timeout_s=query_timeout_s,
    )
    return overpass_elements_to_geojson(elements, limit_ways=None)


async def fetch_highway_geojson_for_center(
    center_lon: float,
    center_lat: float,
    fetch_radius_m: float,
    *,
    max_ways: int,
    timeout_s: float = 20.0,
    query_timeout_s: int = 30,
) -> dict[str, Any]:
    min_lat, min_lon, max_lat, max_lon = center_radius_to_bbox(
        center_lon, center_lat, fetch_radius_m
    )
    return await fetch_highway_geojson_for_bbox(
        min_lat,
        min_lon,
        max_lat,
        max_lon,
        max_ways=max_ways,
        timeout_s=timeout_s,
        query_timeout_s=query_timeout_s,
    )
