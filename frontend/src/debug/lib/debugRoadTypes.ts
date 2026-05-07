/**
 * OSM の道路 way を Overpass で絞り込むときの `highway=*` の値。
 * （タグ名は OSM 仕様どおり `highway`、ここで列挙しているのはその値＝道路種別）
 */
export const DEBUG_ROAD_TYPE_VALUES = [
  'motorway',
  'trunk',
  'primary',
  'secondary',
  'tertiary',
  'unclassified',
  'residential',
] as const

export type DebugRoadType = (typeof DEBUG_ROAD_TYPE_VALUES)[number]

/** motorway のみオフ */
export function defaultDebugRoadTypeSelection(): Record<DebugRoadType, boolean> {
  return Object.fromEntries(
    DEBUG_ROAD_TYPE_VALUES.map((v) => [v, v !== 'motorway']),
  ) as Record<DebugRoadType, boolean>
}
