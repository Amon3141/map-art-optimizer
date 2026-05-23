from app.osm.highway_include import INCLUDED_HIGHWAY_TYPES
from app.osm.overpass import highway_bbox_query


def test_highway_bbox_query_all_highways_when_values_none() -> None:
    q = highway_bbox_query(35.0, 139.0, 35.1, 139.1, highway_values=None)
    assert 'way["highway"]' in q
    assert 'way["highway"~' not in q


def test_highway_bbox_query_filters_included_types() -> None:
    q = highway_bbox_query(
        35.0,
        139.0,
        35.1,
        139.1,
        highway_values=INCLUDED_HIGHWAY_TYPES,
    )
    assert 'way["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|service)$"]' in q
    assert 'way["highway"](' not in q
