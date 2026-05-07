import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'

export function fitMapToLineString(map: MapLibreMap, coords: [number, number][]) {
  if (coords.length === 0) return
  const bounds = new maplibregl.LngLatBounds(coords[0], coords[0])
  for (let i = 1; i < coords.length; i++) {
    bounds.extend(coords[i] as [number, number])
  }
  map.fitBounds(bounds, { padding: 56, maxZoom: 18, duration: 380 })
}
