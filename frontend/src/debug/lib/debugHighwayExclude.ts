/**
 * デバッグ UI: API は bbox 内の highway=* 付き way を全件返す前提で、ここで表示用に除外する値。
 * チェック ON = その highway 値を地図・一覧・グラフから除外。
 */
export const DEBUG_HIGHWAY_EXCLUDE_OPTIONS = [
  'motorway',
  'motorway_link',
  'trunk',
  'trunk_link',
  'construction',
  'proposed',
  'raceway',
  'busway',
] as const

export type DebugHighwayExcludeType = (typeof DEBUG_HIGHWAY_EXCLUDE_OPTIONS)[number]

export type DebugHighwayExcludeSelection = Record<DebugHighwayExcludeType, boolean>

export function defaultDebugHighwayExcludeSelection(): DebugHighwayExcludeSelection {
  return Object.fromEntries(
    DEBUG_HIGHWAY_EXCLUDE_OPTIONS.map((v) => [v, true]),
  ) as DebugHighwayExcludeSelection
}

function excludedHighwaySet(selection: DebugHighwayExcludeSelection): Set<string> {
  const s = new Set<string>()
  for (const key of DEBUG_HIGHWAY_EXCLUDE_OPTIONS) {
    if (selection[key]) s.add(key)
  }
  return s
}

export function filterFeatureCollectionByExcludedHighways(
  fc: GeoJSON.FeatureCollection,
  selection: DebugHighwayExcludeSelection,
): GeoJSON.FeatureCollection {
  const drop = excludedHighwaySet(selection)
  const feats = fc.features.filter((f) => {
    if (f.geometry.type !== 'LineString') return true
    const hw = f.properties && typeof f.properties === 'object' && 'highway' in f.properties
      ? f.properties.highway
      : undefined
    if (hw == null || typeof hw !== 'string') return true
    return !drop.has(hw)
  })
  return { type: 'FeatureCollection', features: feats }
}
