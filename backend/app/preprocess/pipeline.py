"""
RoadGraph 上の前処理オーケストレーション。

処理順（既定）: connect_osm → snap → road_merge → split → prune。
GeoJSON 取り込みは `app.osm.ingest`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .defaults import (
    DEFAULT_CONNECT_OSM_NODE_IDS_ENABLED,
    DEFAULT_MERGE_DUPLICATE_ROADS_ENABLED,
    DEFAULT_REMOVE_REDUNDANT_CHAIN_VERTICES_ENABLED,
    DEFAULT_SPLIT_INTERSECTIONS_ENABLED,
    DEFAULT_SNAP_ENDPOINTS_ENABLED,
    DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M,
    DEFAULT_ROAD_MERGE_ANGLE_DEG,
    DEFAULT_ROAD_MERGE_DISTANCE_M,
    DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_M,
    DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO,
    DEFAULT_SNAP_EPSILON_M,
)
from .graph_model import RoadGraph


@dataclass
class GraphPreprocessOptions:
    connect_osm_node_ids_enabled: bool = DEFAULT_CONNECT_OSM_NODE_IDS_ENABLED

    snap_endpoints_enabled: bool = DEFAULT_SNAP_ENDPOINTS_ENABLED
    snap_epsilon_m: float = DEFAULT_SNAP_EPSILON_M

    merge_duplicate_roads_enabled: bool = DEFAULT_MERGE_DUPLICATE_ROADS_ENABLED
    road_merge_distance_m: float = DEFAULT_ROAD_MERGE_DISTANCE_M
    road_merge_angle_deg: float = DEFAULT_ROAD_MERGE_ANGLE_DEG
    road_merge_min_overlap_m: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_M
    road_merge_min_overlap_ratio: float = DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO
    road_merge_anchor_delta_m: float = DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M
    road_merge_max_anchor_offset_m: float = DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M

    split_intersections_enabled: bool = DEFAULT_SPLIT_INTERSECTIONS_ENABLED

    remove_redundant_chain_vertices_enabled: bool = DEFAULT_REMOVE_REDUNDANT_CHAIN_VERTICES_ENABLED
    prune_chain_accum_angle_deg: float = DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG


def preprocess_road_graph(graph: RoadGraph, options: GraphPreprocessOptions) -> dict[str, Any]:
    """オプションが ON のステップのみ、既定順でグラフに適用し、step_metrics を返す。"""
    step_metrics: dict[str, Any] = {}
    if options.connect_osm_node_ids_enabled:
        from .options.connect_osm import merge_by_osm_node_id

        step_metrics["connect_osm"] = merge_by_osm_node_id(graph)
        step_metrics["connect_osm"]["merged_vertex_count"] = sum(
            1 for n in graph.nodes.values() if n.merged_from_osm_id
        )

    if options.snap_endpoints_enabled:
        from .options.snap_endpoints import snap_endpoints

        step_metrics["snap"] = snap_endpoints(graph, options.snap_epsilon_m)

    if options.merge_duplicate_roads_enabled:
        from .options.merge_duplicate_roads import merge_duplicate_roads

        step_metrics["road_merge"] = merge_duplicate_roads(
            graph,
            max_distance_m=options.road_merge_distance_m,
            max_angle_deg=options.road_merge_angle_deg,
            min_overlap_m=options.road_merge_min_overlap_m,
            min_overlap_ratio=options.road_merge_min_overlap_ratio,
            anchor_delta_m=options.road_merge_anchor_delta_m,
            max_anchor_offset_m=options.road_merge_max_anchor_offset_m,
        )

    if options.split_intersections_enabled:
        from .options.split_intersections import run_intersection_splits

        step_metrics["split"] = run_intersection_splits(graph)

    if options.remove_redundant_chain_vertices_enabled:
        from .options.prune_chains import prune_redundant_chain_vertices

        step_metrics["prune_chains"] = prune_redundant_chain_vertices(
            graph, options.prune_chain_accum_angle_deg
        )

    return step_metrics
