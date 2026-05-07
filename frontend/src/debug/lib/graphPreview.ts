export type GraphBuildOptionsPayload = {
  deduplicate_geometry: boolean
  connect_osm_node_ids: boolean
  snap_endpoints: boolean
  snap_epsilon_m: number
  split_intersections: boolean
}

/** API の step_metrics と整合 */
export type GraphStepMetrics = {
  deduplicate?: {
    way_vertices_before?: number
    way_vertices_after?: number
    removed_duplicate_vertices?: number
  }
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
    dedupe_removed_edges?: GeoJSON.FeatureCollection
    dedupe_removed_vertices?: GeoJSON.FeatureCollection
  }
}

export function defaultGraphBuildOptions(): GraphBuildOptionsPayload {
  return {
    deduplicate_geometry: false,
    connect_osm_node_ids: false,
    snap_endpoints: false,
    snap_epsilon_m: 5,
    split_intersections: false,
  }
}
