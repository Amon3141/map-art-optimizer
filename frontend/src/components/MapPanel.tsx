import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { BasemapSelector, type BasemapMode } from './BasemapSelector'
import {
  DEBUG_BASEMAP_STYLE,
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  applyDebugBasemapVisibility,
} from '../debug/lib/debugMapBasemap'
import { circlePolygon } from '../lib/geoUtils'

const FETCH_RANGE_SOURCE = 'prod-fetch-range'
const FETCH_RANGE_FILL_LAYER = 'prod-fetch-range-fill'
const FETCH_RANGE_LINE_LAYER = 'prod-fetch-range-line'
const ROUTE_SOURCE = 'prod-route-overlay'
const ROUTE_LAYER = 'prod-route-overlay-line'

export type MapPanelProps = {
  className?: string
  onMapReady?: (map: MapLibreMap) => void
  onCenterChange?: (lon: number, lat: number) => void
  routeGeoJson?: GeoJSON.FeatureCollection | null
  fetchRangeCircle?: { lon: number; lat: number; radiusM: number } | null
}

export function MapPanel({
  className = '',
  onMapReady,
  onCenterChange,
  routeGeoJson,
  fetchRangeCircle,
}: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onMapReadyRef = useRef(onMapReady)
  const onCenterChangeRef = useRef(onCenterChange)
  const basemapModeRef = useRef<BasemapMode>('light')
  const [mapReady, setMapReady] = useState(false)
  const [basemapMode, setBasemapMode] = useState<BasemapMode>('light')

  onMapReadyRef.current = onMapReady
  onCenterChangeRef.current = onCenterChange
  basemapModeRef.current = basemapMode

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let cancelled = false
    const map = new maplibregl.Map({
      container: el,
      style: DEBUG_BASEMAP_STYLE,
      center: DEFAULT_MAP_CENTER,
      zoom: DEFAULT_MAP_ZOOM,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    const resize = () => map.resize()
    window.addEventListener('resize', resize)

    const ro = new ResizeObserver(() => map.resize())
    ro.observe(el)

    map.once('load', () => {
      if (cancelled || mapRef.current !== map) return
      map.resize()
      requestAnimationFrame(() => {
        if (cancelled || mapRef.current !== map) return
        map.resize()
        applyDebugBasemapVisibility(map, basemapModeRef.current)

        // 探索範囲 circle（ルート overlay の下に追加）
        map.addSource(FETCH_RANGE_SOURCE, {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        })
        map.addLayer({
          id: FETCH_RANGE_FILL_LAYER,
          type: 'fill',
          source: FETCH_RANGE_SOURCE,
          paint: { 'fill-color': '#c45c3e', 'fill-opacity': 0.06 },
        })
        map.addLayer({
          id: FETCH_RANGE_LINE_LAYER,
          type: 'line',
          source: FETCH_RANGE_SOURCE,
          paint: {
            'line-color': '#c45c3e',
            'line-width': 1.5,
            'line-opacity': 0.45,
            'line-dasharray': [5, 3],
          },
        })

        // ルートオーバーレイ（探索範囲の上に追加）
        map.addSource(ROUTE_SOURCE, {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        })
        map.addLayer({
          id: ROUTE_LAYER,
          type: 'line',
          source: ROUTE_SOURCE,
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#c45c3e', 'line-width': 4, 'line-opacity': 0.85 },
        })
      })
      onMapReadyRef.current?.(map)
      setMapReady(true)
    })

    const onMoveEnd = () => {
      const center = map.getCenter()
      onCenterChangeRef.current?.(center.lng, center.lat)
    }
    map.on('moveend', onMoveEnd)

    return () => {
      cancelled = true
      ro.disconnect()
      window.removeEventListener('resize', resize)
      map.off('moveend', onMoveEnd)
      map.remove()
      mapRef.current = null
      setMapReady(false)
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return
    applyDebugBasemapVisibility(map, basemapMode)
  }, [mapReady, basemapMode])

  // 探索範囲 circle の更新
  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return
    const source = map.getSource(FETCH_RANGE_SOURCE) as maplibregl.GeoJSONSource | undefined
    if (!source) return
    if (!fetchRangeCircle) {
      source.setData({ type: 'FeatureCollection', features: [] })
      return
    }
    source.setData({
      type: 'FeatureCollection',
      features: [
        circlePolygon(fetchRangeCircle.lon, fetchRangeCircle.lat, fetchRangeCircle.radiusM),
      ],
    })
  }, [mapReady, fetchRangeCircle])

  // ルートオーバーレイの更新
  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return
    const source = map.getSource(ROUTE_SOURCE) as maplibregl.GeoJSONSource | undefined
    if (!source) return
    source.setData(routeGeoJson ?? { type: 'FeatureCollection', features: [] })
  }, [mapReady, routeGeoJson])

  return (
    <div className={`relative min-h-0 w-full min-w-0 flex-1 ${className}`}>
      <div ref={containerRef} className="absolute inset-0" />
      <div
        className="pointer-events-none absolute inset-0 z-1 shadow-[inset_0_4px_40px_0_rgb(62_36_30/0.095),inset_0_0_280px_0_rgb(48_28_24/0.115)]"
        aria-hidden
      />
      <div className="pointer-events-none absolute left-3 top-3 z-10 sm:left-4 sm:top-4">
        <BasemapSelector value={basemapMode} onChange={setBasemapMode} />
      </div>
    </div>
  )
}
