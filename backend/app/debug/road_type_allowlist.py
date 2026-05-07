# デバッグ GET /api/debug/ways で許可する OSM highway=* の値（Overpass にそのまま渡す）
DEBUG_ROAD_TYPE_ALLOWLIST: frozenset[str] = frozenset(
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
