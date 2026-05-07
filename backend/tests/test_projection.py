"""Projection round-trip sanity check."""

from app.osm.projection import EARTH_RADIUS_M, lon_lat_to_xy_m, xy_m_to_lon_lat


def test_lon_lat_roundtrip_tokyo_center():
    lon0, lat0 = 139.77, 35.68
    lon, lat = 139.775, 35.685
    x, y = lon_lat_to_xy_m(lon0, lat0, lon, lat)
    lon2, lat2 = xy_m_to_lon_lat(lon0, lat0, x, y)
    assert abs(lon2 - lon) < 1e-6
    assert abs(lat2 - lat) < 1e-6


def test_xy_roundtrip():
    lon0, lat0 = 0.0, 45.0
    x, y = 100.0, -50.0
    lon, lat = xy_m_to_lon_lat(lon0, lat0, x, y)
    x2, y2 = lon_lat_to_xy_m(lon0, lat0, lon, lat)
    assert abs(x2 - x) < 1e-3
    assert abs(y2 - y) < 1e-3


def test_earth_radius_constant():
    assert EARTH_RADIUS_M == 6_371_000.0
