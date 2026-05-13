"""OSM way → road graph pipeline (debug / preprocess). Public API re-exported here."""

from .defaults import (
    DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
    DEFAULT_ROAD_MERGE_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_DISTANCE_M,
    DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
)
from .pipeline import (
    GraphBuildOptions,
    GraphBuildResult,
    WayPolyline,
    apply_all_graph_build_options,
    build_graph_from_geojson,
    build_native_graph,
    classify_vertex_role,
    graph_to_geojson_fc,
    parse_way_features,
)

__all__ = [
    "DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG",
    "DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M",
    "DEFAULT_ROAD_MERGE_ANGLE_DEG",
    "DEFAULT_ROAD_MERGE_DISTANCE_M",
    "DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M",
    "DEFAULT_ROAD_MERGE_MIN_OVERLAP_M",
    "DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO",
    "GraphBuildOptions",
    "GraphBuildResult",
    "WayPolyline",
    "apply_all_graph_build_options",
    "build_graph_from_geojson",
    "build_native_graph",
    "classify_vertex_role",
    "graph_to_geojson_fc",
    "parse_way_features",
]
