/** デバッグ取得で選べる OSM highway=* の値（Overpass のフィルタと一致） */
export const DEBUG_HIGHWAY_VALUES = [
  'motorway',
  'trunk',
  'primary',
  'secondary',
  'tertiary',
  'unclassified',
  'residential',
] as const

export type DebugHighwayValue = (typeof DEBUG_HIGHWAY_VALUES)[number]

export function defaultDebugHighwaySelection(): Record<DebugHighwayValue, boolean> {
  const on: DebugHighwayValue[] = ['motorway', 'trunk']
  return Object.fromEntries(
    DEBUG_HIGHWAY_VALUES.map((v) => [v, on.includes(v)]),
  ) as Record<DebugHighwayValue, boolean>
}
