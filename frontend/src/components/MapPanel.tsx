import maplibregl, { type LngLatBoundsLike, type Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { BasemapSelector, type BasemapMode } from './BasemapSelector'

export type MapPanelProps = {
  className?: string
  overlayGeoJson?: GeoJSON.FeatureCollection | null
  overlayLineColor?: string
  overlaySelectedId?: number | string | null
  overlayHighlightColor?: string
  /** false のとき、オーバーレイ更新で地図の表示範囲（カメラ）を変えない */
  fitOverlayToData?: boolean
  onMapReady?: (map: MapLibreMap) => void
}

const DEFAULT_CENTER: [number, number] = [139.7671, 35.6812]
const DEFAULT_ZOOM = 12

const OVERLAY_SRC = 'debug-overlay'
const OVERLAY_LINE = 'debug-overlay-line'

const BASEMAP_OSM = 'basemap-osm'
const BASEMAP_LIGHT = 'basemap-light'
const BASEMAP_DARK = 'basemap-dark'

/** OSM + Carto（ライト／ダーク）を同一スタイルに載せ、visibility で切り替え（オーバーレイを保つ） */
const BASEMAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
    carto_light: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
    carto_dark: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [
    {
      id: BASEMAP_OSM,
      type: 'raster',
      source: 'osm',
      minzoom: 0,
      maxzoom: 19,
      layout: { visibility: 'visible' },
    },
    {
      id: BASEMAP_LIGHT,
      type: 'raster',
      source: 'carto_light',
      minzoom: 0,
      maxzoom: 20,
      layout: { visibility: 'none' },
    },
    {
      id: BASEMAP_DARK,
      type: 'raster',
      source: 'carto_dark',
      minzoom: 0,
      maxzoom: 20,
      layout: { visibility: 'none' },
    },
  ],
}

function applyBasemapVisibility(map: MapLibreMap, mode: BasemapMode) {
  for (const id of [BASEMAP_OSM, BASEMAP_LIGHT, BASEMAP_DARK]) {
    if (!map.getLayer(id)) return
  }
  const osmVis = mode === 'normal' ? 'visible' : 'none'
  const lightVis = mode === 'light' ? 'visible' : 'none'
  const darkVis = mode === 'dark' ? 'visible' : 'none'
  map.setLayoutProperty(BASEMAP_OSM, 'visibility', osmVis)
  map.setLayoutProperty(BASEMAP_LIGHT, 'visibility', lightVis)
  map.setLayoutProperty(BASEMAP_DARK, 'visibility', darkVis)
}

function removeOverlayLayersAndSource(map: MapLibreMap) {
  if (map.getLayer(OVERLAY_LINE)) map.removeLayer(OVERLAY_LINE)
  if (map.getSource(OVERLAY_SRC)) map.removeSource(OVERLAY_SRC)
}

function fitOverlayBounds(map: MapLibreMap, overlayGeoJson: GeoJSON.FeatureCollection) {
  const bounds = new maplibregl.LngLatBounds()
  let any = false
  for (const f of overlayGeoJson.features) {
    if (f.geometry.type === 'LineString') {
      for (const c of f.geometry.coordinates as [number, number][]) {
        bounds.extend(c as [number, number])
        any = true
      }
    }
  }
  if (any) {
    map.fitBounds(bounds as LngLatBoundsLike, { padding: 48, maxZoom: 16, duration: 0 })
  }
}

/** overlaySelectedId を feature プロパティ `_selected` として注入した GeoJSON を返す */
function injectSelected(
  g: GeoJSON.FeatureCollection,
  selectedId: number | string | null | undefined,
): GeoJSON.FeatureCollection {
  const key = selectedId != null ? String(selectedId) : null
  return {
    ...g,
    features: g.features.map((f) => ({
      ...f,
      properties: {
        ...f.properties,
        _selected: key != null && String(f.properties?.osm_way_id) === key ? 1 : 0,
      },
    })),
  }
}

export function MapPanel({
  className = '',
  overlayGeoJson,
  overlayLineColor = '#c45c3e',
  overlaySelectedId = null,
  overlayHighlightColor = '#3b9ede',
  fitOverlayToData = true,
  onMapReady,
}: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onMapReadyRef = useRef(onMapReady)
  const basemapModeRef = useRef<BasemapMode>('normal')
  const [mapReady, setMapReady] = useState(false)
  const [basemapMode, setBasemapMode] = useState<BasemapMode>('normal')

  onMapReadyRef.current = onMapReady
  basemapModeRef.current = basemapMode

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let cancelled = false
    const map = new maplibregl.Map({
      container: el,
      style: BASEMAP_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    const resize = () => map.resize()
    window.addEventListener('resize', resize)

    const ro = new ResizeObserver(() => {
      map.resize()
    })
    ro.observe(el)

    map.once('load', () => {
      if (cancelled || mapRef.current !== map) return
      map.resize()
      requestAnimationFrame(() => {
        if (cancelled || mapRef.current !== map) return
        map.resize()
        applyBasemapVisibility(map, basemapModeRef.current)
      })
      onMapReadyRef.current?.(map)
      setMapReady(true)
    })

    return () => {
      cancelled = true
      ro.disconnect()
      window.removeEventListener('resize', resize)
      map.remove()
      mapRef.current = null
      setMapReady(false)
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return
    applyBasemapVisibility(map, basemapMode)
  }, [mapReady, basemapMode])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    const g = overlayGeoJson
    if (!g || g.features.length === 0) {
      removeOverlayLayersAndSource(map)
      return
    }

    const data = injectSelected(g, overlaySelectedId)
    const lineColor: maplibregl.ExpressionSpecification = [
      'case',
      ['==', ['get', '_selected'], 1],
      overlayHighlightColor,
      overlayLineColor,
    ]

    const src = map.getSource(OVERLAY_SRC) as maplibregl.GeoJSONSource | undefined
    if (!src) {
      map.addSource(OVERLAY_SRC, { type: 'geojson', data })
      map.addLayer({
        id: OVERLAY_LINE,
        type: 'line',
        source: OVERLAY_SRC,
        paint: { 'line-color': lineColor, 'line-width': 4, 'line-opacity': 0.85 },
      })
      if (fitOverlayToData) fitOverlayBounds(map, g)
      return
    }

    src.setData(data)
    map.setPaintProperty(OVERLAY_LINE, 'line-color', lineColor)
    if (fitOverlayToData) fitOverlayBounds(map, g)
  }, [mapReady, overlayGeoJson, overlaySelectedId, overlayLineColor, overlayHighlightColor, fitOverlayToData])

  return (
    <div className={`relative min-h-0 w-full min-w-0 flex-1 ${className}`}>
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-3 top-3 z-10 sm:left-4 sm:top-4">
        <BasemapSelector value={basemapMode} onChange={setBasemapMode} />
      </div>
    </div>
  )
}
