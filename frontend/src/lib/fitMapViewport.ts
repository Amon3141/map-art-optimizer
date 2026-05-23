import maplibregl, { type LngLatBoundsLike, type Map as MapLibreMap } from 'maplibre-gl'

type LonLat = [number, number]

const DEFAULT_PADDING = 56
/** ルート結果の fitBounds 用（周囲余白を多めに） */
export const ROUTE_FIT_PADDING = 96
const DEFAULT_MAX_ZOOM = 18
const DEFAULT_FLY_DURATION_MS = 380
/** Ideal zoom よりこの分だけ低いときは「引きすぎ」とみなす */
const ZOOM_SLACK = 0.75
/** ルートの画面占有がこれ未満なら「小さすぎ」として fit */
const MIN_ROUTE_SCREEN_FRACTION = 0.45

export type FitMapViewportOptions = {
  padding?: number
  maxZoom?: number
  flyDurationMs?: number
  /** true → duration 0 (bulk graph/OSM load) */
  instant?: boolean
  /** true → ルートが viewport 内かつ zoom 十分なら fitBounds しない */
  onlyIfNeeded?: boolean
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

function routeFitsInViewport(
  map: MapLibreMap,
  routeBounds: maplibregl.LngLatBounds,
  padding: number,
): boolean {
  const el = map.getContainer()
  const maxX = el.clientWidth - padding
  const maxY = el.clientHeight - padding
  const corners = [
    routeBounds.getNorthWest(),
    routeBounds.getNorthEast(),
    routeBounds.getSouthWest(),
    routeBounds.getSouthEast(),
  ]
  for (const lngLat of corners) {
    const px = map.project(lngLat)
    if (px.x < padding || px.y < padding || px.x > maxX || px.y > maxY) {
      return false
    }
  }
  return true
}

function isZoomTooLow(
  map: MapLibreMap,
  routeBounds: maplibregl.LngLatBounds,
  padding: number,
  maxZoom: number,
): boolean {
  const camera = map.cameraForBounds(routeBounds as LngLatBoundsLike, { padding, maxZoom })
  if (camera?.zoom == null) return true
  return map.getZoom() < camera.zoom - ZOOM_SLACK
}

/** bbox の投影が viewport の十分な割合を占めていない（探索直後の広域表示など） */
function isRouteUnderframed(
  map: MapLibreMap,
  routeBounds: maplibregl.LngLatBounds,
  padding: number,
): boolean {
  const nw = map.project(routeBounds.getNorthWest())
  const se = map.project(routeBounds.getSouthEast())
  const routeW = Math.abs(se.x - nw.x)
  const routeH = Math.abs(se.y - nw.y)
  const el = map.getContainer()
  const availW = Math.max(1, el.clientWidth - 2 * padding)
  const availH = Math.max(1, el.clientHeight - 2 * padding)
  return (
    routeW < availW * MIN_ROUTE_SCREEN_FRACTION ||
    routeH < availH * MIN_ROUTE_SCREEN_FRACTION
  )
}

/** true → fitBounds が必要（収まっていない、zoom 不足、またはルートが画面上で小さすぎ） */
export function shouldFitMapToRoute(
  map: MapLibreMap,
  routeBounds: maplibregl.LngLatBounds,
  options?: Pick<FitMapViewportOptions, 'padding' | 'maxZoom'>,
): boolean {
  const padding = options?.padding ?? DEFAULT_PADDING
  const maxZoom = options?.maxZoom ?? DEFAULT_MAX_ZOOM
  if (!routeFitsInViewport(map, routeBounds, padding)) return true
  if (isRouteUnderframed(map, routeBounds, padding)) return true
  if (isZoomTooLow(map, routeBounds, padding, maxZoom)) return true
  return false
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

  if (options?.onlyIfNeeded && !shouldFitMapToRoute(map, bounds, { padding, maxZoom })) {
    return
  }

  const duration = options?.instant
    ? 0
    : shouldAnimateFit(map, bounds)
      ? flyDurationMs
      : 0

  map.stop()
  map.fitBounds(bounds as LngLatBoundsLike, { padding, maxZoom, duration })
}

/**
 * Fit viewport after map load and layout settle (e.g. overlay unmount resize).
 * Returns cleanup to cancel pending work.
 */
export function fitMapWhenReady(
  map: MapLibreMap,
  fc: GeoJSON.FeatureCollection,
  options?: FitMapViewportOptions,
): () => void {
  if (fc.features.length === 0) return () => {}

  let cancelled = false
  let raf1 = 0
  let raf2 = 0
  let raf3 = 0

  const runFit = () => {
    if (cancelled || !map.loaded()) return
    fitMapToFeatureCollections(map, fc, options)
  }

  const scheduleFit = () => {
    if (cancelled) return
    cancelAnimationFrame(raf1)
    cancelAnimationFrame(raf2)
    cancelAnimationFrame(raf3)
    // オーバーレイ解除・パネル展開後の resize を待つ（3 段 rAF）
    raf1 = requestAnimationFrame(() => {
      if (cancelled) return
      raf2 = requestAnimationFrame(() => {
        if (cancelled) return
        raf3 = requestAnimationFrame(runFit)
      })
    })
  }

  const onLoad = () => scheduleFit()

  if (map.loaded()) {
    scheduleFit()
  } else {
    map.once('load', onLoad)
  }

  return () => {
    cancelled = true
    cancelAnimationFrame(raf1)
    cancelAnimationFrame(raf2)
    cancelAnimationFrame(raf3)
    map.off('load', onLoad)
  }
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
