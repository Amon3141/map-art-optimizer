"""Overpass API（/api/interpreter）への非同期 HTTP クライアント。"""

import os
from typing import Any

import httpx

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

_DEFAULT_HEADERS = {
    "User-Agent": "map-draw-optimizer/0.1 (local dev; contact: local)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


async def fetch_interpreter(query: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(OVERPASS_URL, content=query.encode(), headers=_DEFAULT_HEADERS)
        r.raise_for_status()
        return r.json()
