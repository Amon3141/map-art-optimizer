/**
 * デバッグ UI: API は bbox 内の highway=* 付き way を全件返す前提で、ここで表示用に含める値を選ぶ。
 * チェック ON = その highway 値の LineString を地図・一覧・グラフに含める。
 */
const DEBUG_HIGHWAY_TAGS_ALL = [
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

/** 既定で含める（チェック ON） */
const DEBUG_HIGHWAY_INCLUDE_DEFAULT_ON = new Set<string>([
  'trunk',
  'primary',
  'secondary',
  'tertiary',
  'unclassified',
  'residential',
  'service'
])

export type DebugHighwayTag = (typeof DEBUG_HIGHWAY_TAGS_ALL)[number]

export const DEBUG_HIGHWAY_TAG_OPTIONS: readonly DebugHighwayTag[] = [...DEBUG_HIGHWAY_TAGS_ALL].sort((a, b) =>
  a.localeCompare(b),
)

export type DebugHighwayIncludeSelection = Record<DebugHighwayTag, boolean>

export function defaultDebugHighwayIncludeSelection(): DebugHighwayIncludeSelection {
  return Object.fromEntries(
    DEBUG_HIGHWAY_TAG_OPTIONS.map((v) => [v, DEBUG_HIGHWAY_INCLUDE_DEFAULT_ON.has(v)]),
  ) as DebugHighwayIncludeSelection
}

const knownHighway = new Set<string>(DEBUG_HIGHWAY_TAG_OPTIONS)

export function filterFeatureCollectionByIncludedHighways(
  fc: GeoJSON.FeatureCollection,
  selection: DebugHighwayIncludeSelection,
): GeoJSON.FeatureCollection {
  const feats = fc.features.filter((f) => {
    if (f.geometry.type !== 'LineString') return true
    const hw =
      f.properties && typeof f.properties === 'object' && 'highway' in f.properties
        ? f.properties.highway
        : undefined
    if (hw == null || typeof hw !== 'string') return true
    if (!knownHighway.has(hw)) return false
    return selection[hw as DebugHighwayTag] === true
  })
  return { type: 'FeatureCollection', features: feats }
}
