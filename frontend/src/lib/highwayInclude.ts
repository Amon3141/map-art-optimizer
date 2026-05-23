/** 道路ネットワークに含める highway=* 値。backend/app/osm/highway_include.py と同期して保つ。 */

export const INCLUDED_HIGHWAY_TYPES = [
  'trunk',
  'primary',
  'secondary',
  'tertiary',
  'unclassified',
  'residential',
  'service',
] as const

export type IncludedHighwayType = (typeof INCLUDED_HIGHWAY_TYPES)[number]
