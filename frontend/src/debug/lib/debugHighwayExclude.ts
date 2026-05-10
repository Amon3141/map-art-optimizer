/**
 * デバッグ UI: API は bbox 内の highway=* 付き way を全件返す前提で、ここで表示用に除外する値。
 * チェック ON = その highway 値を地図・一覧・グラフから除外。
 */
const DEBUG_HIGHWAY_EXCLUDE_ALL = [
  'abandoned',
  'bridleway',
  'bus_guideway',
  'busway',
  'construction',
  'corridor',
  'crossing',
  'cycleway',
  'disused',
  'elevator',
  'escalator',
  'escape',
  'footway',
  'ford',
  'junction',
  'living_street',
  'motorway',
  'motorway_junction',
  'motorway_link',
  'moving_walkway',
  'path',
  'pedestrian',
  'platform',
  'primary',
  'primary_link',
  'proposed',
  'raceway',
  'residential',
  'rest_area',
  'road',
  'secondary',
  'secondary_link',
  'service',
  'services',
  'steps',
  'tertiary',
  'tertiary_link',
  'track',
  'trunk',
  'trunk_link',
  'unclassified',
  'via_ferrata',
] as const

/** 既定で除外 ON（従来のデフォルトのまま） */
const DEBUG_HIGHWAY_EXCLUDE_DEFAULT_ON = new Set<string>([
  'motorway',
  'motorway_link',
  'trunk',
  'trunk_link',
  'construction',
  'proposed',
  'raceway',
  'busway',
])

export type DebugHighwayExcludeType = (typeof DEBUG_HIGHWAY_EXCLUDE_ALL)[number]

export const DEBUG_HIGHWAY_EXCLUDE_OPTIONS: readonly DebugHighwayExcludeType[] = [
  ...DEBUG_HIGHWAY_EXCLUDE_ALL,
].sort((a, b) => a.localeCompare(b))

export type DebugHighwayExcludeSelection = Record<DebugHighwayExcludeType, boolean>

export function defaultDebugHighwayExcludeSelection(): DebugHighwayExcludeSelection {
  return Object.fromEntries(
    DEBUG_HIGHWAY_EXCLUDE_OPTIONS.map((v) => [v, DEBUG_HIGHWAY_EXCLUDE_DEFAULT_ON.has(v)]),
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
