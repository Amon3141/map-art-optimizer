/** 最適化 API レスポンスの型定義。 */

export type OptimizeTraceStep = {
  step_index: number
  temperature: number
  accepted: boolean
  score_total: number
  score_terms: Record<string, number>
  transform: Record<string, number>
  edge_ids: string[]
  edge_ids_per_component?: string[][]
}

export type OptimizeRestartResult = {
  restart_index: number
  seed: number
  initial_transform: Record<string, number>
  best_transform: Record<string, number>
  best_edge_ids: string[]
  best_score: number
  best_breakdown: Record<string, number>
  route_length_m?: number
  route_length_km?: number
  iterations_planned: number
  iterations_completed: number
  accepted_moves: number
  acceptance_rate: number
  deadline_hit: boolean
  trace_steps: OptimizeTraceStep[]
}

export type OptimizeComponentResult = {
  component_index: number
  best_score: number
  best_breakdown: Record<string, number>
  route_length_m: number
  route_length_km: number
}

export type RankedOptimizeCandidate = {
  candidate_id: string
  rank: number
  restart_index: number
  step_index: number
  score_total: number
  score_delta_from_best: number
  tier: 'best' | 'included'
  route_length_m: number
  route_length_km: number
  transform: Record<string, number>
  edge_ids: string[]
  edge_ids_per_component?: string[][]
  labels: string[]
  score_terms: Record<string, number>
}

export type OptimizeProjection = {
  lon0: number
  lat0: number
  mode: string
}

export type OptimizeApiResponse = {
  projection: OptimizeProjection
  candidates_geojson: GeoJSON.FeatureCollection
  ranked_candidates?: RankedOptimizeCandidate[]
  candidate_selection_meta?: Record<string, number>
  best_score: number
  best_breakdown: Record<string, number>
  best_restart_index: number
  route_length_m?: number
  route_length_km?: number
  optimizer_meta?: Record<string, unknown>
  restarts: OptimizeRestartResult[]
  components?: OptimizeComponentResult[]
  /** トレース再生用のエッジ GeoJSON（/api/optimize が返す） */
  edges_geojson?: GeoJSON.FeatureCollection
  /** /api/debug/optimize が返すトレースフォーマットバージョン */
  trace_format_version?: number
  stats?: Record<string, number>
}
