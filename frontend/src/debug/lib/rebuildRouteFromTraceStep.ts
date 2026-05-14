type LonLat = [number, number]

/** `graph-preview` の edges FeatureCollection から internal_edge_id → 座標列 */
export function edgeGeometriesById(edgesFc: GeoJSON.FeatureCollection): Map<string, LonLat[]> {
  const m = new Map<string, LonLat[]>()
  for (const f of edgesFc.features) {
    if (f.geometry.type !== 'LineString') continue
    const id = f.properties?.internal_edge_id
    if (id == null) continue
    m.set(String(id), f.geometry.coordinates as LonLat[])
  }
  return m
}

function dist2(a: LonLat, b: LonLat): number {
  const dx = a[0] - b[0]
  const dy = a[1] - b[1]
  return dx * dx + dy * dy
}

/** エッジ ID 列から WGS84 LineString 座標を連結（隣接エッジの向きを揃える） */
export function coordinatesFromEdgeIds(
  edgeIds: string[],
  byId: Map<string, LonLat[]>,
): LonLat[] {
  if (edgeIds.length === 0) return []
  let out: LonLat[] = []
  let last: LonLat | null = null

  for (const eid of edgeIds) {
    let pl = byId.get(eid)
    if (!pl || pl.length < 2) continue
    pl = [...pl]
    if (last) {
      const d0 = dist2(pl[0], last)
      const d1 = dist2(pl[pl.length - 1], last)
      if (d1 < d0) pl.reverse()
    }
    if (out.length && pl.length) {
      if (dist2(pl[0], out[out.length - 1]!) < 1e-14) pl = pl.slice(1)
    }
    out = out.concat(pl)
    last = out[out.length - 1] ?? null
  }
  return out
}

export function rebuildRouteFeatureCollection(
  edgeIds: string[],
  edgesFc: GeoJSON.FeatureCollection,
): GeoJSON.FeatureCollection {
  const byId = edgeGeometriesById(edgesFc)
  const coords = coordinatesFromEdgeIds(edgeIds, byId)
  if (coords.length < 2) {
    return { type: 'FeatureCollection', features: [] }
  }
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { source: 'optimization_trace' },
        geometry: { type: 'LineString', coordinates: coords },
      },
    ],
  }
}
