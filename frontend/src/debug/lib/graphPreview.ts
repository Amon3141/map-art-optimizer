export type GraphBuildOptionsPayload = {
  connect_osm_node_ids: boolean
  snap_endpoints: boolean
  snap_epsilon_m: number
  merge_duplicate_roads: boolean
  road_merge_distance_m: number
  road_merge_angle_deg: number
  road_merge_min_overlap_m: number
  road_merge_min_overlap_ratio: number
  road_merge_anchor_delta_m: number
  split_intersections: boolean
  remove_redundant_chain_vertices: boolean
  prune_chain_accum_angle_deg: number
}

/** API の step_metrics と整合 */
export type GraphStepMetrics = {
  connect_osm?: {
    osm_id_groups_merged?: number
    graph_vertices_removed_by_merge?: number
    merged_vertex_count?: number
  }
  split?: {
    intersection_splits_applied?: number
    new_vertices_from_split?: number
  }
  snap?: {
    epsilon_m?: number
    snap_clusters?: number
    vertices_merged_by_snap?: number
  }
  road_merge?: {
    candidate_pairs?: number
    directed_edges?: number
    direction_repaired_edges?: number
    outdegree_pruned_edges?: number
    cycle_edges_removed?: number
    merge_batches_applied?: number
    source_edges_removed?: number
    anchors_created?: number
    incident_edges_remapped?: number
    anchor_delta_m?: number
    distance_m?: number
    angle_deg?: number
    min_overlap_m?: number
    min_overlap_ratio?: number
  }
  prune_chains?: {
    vertices_removed?: number
    angle_accum_threshold_deg?: number
  }
}

export type GraphPreviewResponse = {
  projection: {
    lon0: number
    lat0: number
    mode: string
    summary?: string
  }
  projection_summary?: string
  stats: Record<string, number>
  step_metrics?: GraphStepMetrics
  graph_geojson: {
    nodes: GeoJSON.FeatureCollection
    edges: GeoJSON.FeatureCollection
  }
}

export function defaultGraphBuildOptions(): GraphBuildOptionsPayload {
  return {
    connect_osm_node_ids: false,
    snap_endpoints: false,
    snap_epsilon_m: 3,
    merge_duplicate_roads: false,
    road_merge_distance_m: 14,
    road_merge_angle_deg: 22,
    road_merge_min_overlap_m: 8,
    road_merge_min_overlap_ratio: 0.25,
    road_merge_anchor_delta_m: 2,
    split_intersections: false,
    remove_redundant_chain_vertices: false,
    prune_chain_accum_angle_deg: 15,
  }
}
