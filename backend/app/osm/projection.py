"""local tangent plane at reference (lon0, lat0)."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def lon_lat_to_xy_m(lon0: float, lat0: float, lon: float, lat: float) -> tuple[float, float]:
    """x east (m), y north (m)."""
    lat0_r = math.radians(lat0)
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    x = EARTH_RADIUS_M * math.cos(lat0_r) * dlon
    y = EARTH_RADIUS_M * dlat
    return x, y


def xy_m_to_lon_lat(lon0: float, lat0: float, x: float, y: float) -> tuple[float, float]:
    lat0_r = math.radians(lat0)
    dlat = y / EARTH_RADIUS_M
    lat = lat0 + math.degrees(dlat)
    cos0 = math.cos(lat0_r)
    if abs(cos0) < 1e-9:
        cos0 = 1e-9 if cos0 >= 0 else -1e-9
    dlon = x / (EARTH_RADIUS_M * cos0)
    lon = lon0 + math.degrees(dlon)
    return lon, lat


def bbox_center_lon_lat(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
) -> tuple[float, float]:
    return (min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0
