/** OSM overlay: 一覧で選択した way をライン色でハイライトするための `_selected` を付与 */
export function injectOsmOverlaySelection(
  g: GeoJSON.FeatureCollection,
  overlaySelectedId: number | string | null,
): GeoJSON.FeatureCollection {
  const primary = overlaySelectedId != null ? String(overlaySelectedId) : null
  return {
    ...g,
    features: g.features.map((f) => {
      const pid = f.properties?.osm_way_id
      const sid = pid != null ? String(pid) : null
      const sel = primary != null && sid === primary ? 1 : 0
      return {
        ...f,
        properties: {
          ...f.properties,
          _selected: sel,
        },
      }
    }),
  }
}
