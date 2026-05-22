import maplibregl, { type LngLatBoundsLike, type Map as MapLibreMap } from 'maplibre-gl'

type LonLat = [number, number]

const DEFAULT_PADDING = 56
const DEFAULT_MAX_ZOOM = 18
const DEFAULT_FLY_DURATION_MS = 380

export type FitMapViewportOptions = {
  padding?: number
  maxZoom?: number
  flyDurationMs?: number
  /** true → duration 0 (bulk graph/OSM load) */
  instant?: boolean
}

function isFitMapViewportOptions(x: unknown): x is FitMapViewportOptions {
  return x != null && typeof x === 'object' && !('type' in x)
}

function extendBoundsWithCoords(bounds: maplibregl.LngLatBounds, coords: LonLat[]): boolean {
  if (coords.length === 0) return false
  for (const c of coords) bounds.extend(c)
  return true
}

function extendBoundsWithGeometry(
  bounds: maplibregl.LngLatBounds,
  geometry: GeoJSON.Geometry,
): boolean {
  switch (geometry.type) {
    case 'LineString':
      return extendBoundsWithCoords(bounds, geometry.coordinates as LonLat[])
    case 'MultiLineString': {
      let any = false
      for (const line of geometry.coordinates) {
        if (extendBoundsWithCoords(bounds, line as LonLat[])) any = true
      }
      return any
    }
    case 'Point':
      bounds.extend(geometry.coordinates as LonLat)
      return true
    default:
      return false
  }
}

export function boundsFromFeatureCollection(
  fc: GeoJSON.FeatureCollection,
): maplibregl.LngLatBounds | null {
  const bounds = new maplibregl.LngLatBounds()
  let any = false
  for (const f of fc.features) {
    const g = f.geometry
    if (!g) continue
    if (extendBoundsWithGeometry(bounds, g)) any = true
  }
  return any ? bounds : null
}

function shouldAnimateFit(map: MapLibreMap, target: maplibregl.LngLatBounds): boolean {
  const view = map.getBounds()
  const center = target.getCenter()
  if (view.contains(center)) return true
  return view.intersects(target)
}

export function fitMapToFeatureCollections(
  map: MapLibreMap,
  ...collectionsAndOptions: (
    | GeoJSON.FeatureCollection
    | null
    | undefined
    | FitMapViewportOptions
  )[]
): void {
  const args = [...collectionsAndOptions]
  const last = args[args.length - 1]
  const options: FitMapViewportOptions | undefined = isFitMapViewportOptions(last)
    ? (args.pop() as FitMapViewportOptions)
    : undefined

  const collections = args.filter(
    (c): c is GeoJSON.FeatureCollection =>
      c != null && typeof c === 'object' && 'type' in c && c.type === 'FeatureCollection',
  )

  const bounds = new maplibregl.LngLatBounds()
  let any = false
  for (const coll of collections) {
    const b = boundsFromFeatureCollection(coll)
    if (!b) continue
    any = true
    bounds.extend(b.getNorthWest())
    bounds.extend(b.getSouthEast())
  }
  if (!any) return

  const padding = options?.padding ?? DEFAULT_PADDING
  const maxZoom = options?.maxZoom ?? DEFAULT_MAX_ZOOM
  const flyDurationMs = options?.flyDurationMs ?? DEFAULT_FLY_DURATION_MS
  const duration =
    options?.instant || !shouldAnimateFit(map, bounds) ? 0 : flyDurationMs

  map.fitBounds(bounds as LngLatBoundsLike, { padding, maxZoom, duration })
}

export function fitMapToLineString(
  map: MapLibreMap,
  coords: [number, number][],
  options?: FitMapViewportOptions,
): void {
  if (coords.length === 0) return
  const fc: GeoJSON.FeatureCollection = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: { type: 'LineString', coordinates: coords },
      },
    ],
  }
  fitMapToFeatureCollections(map, fc, options)
}
