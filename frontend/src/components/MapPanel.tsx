import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { BasemapSelector, type BasemapMode } from './BasemapSelector'
import {
  DEBUG_BASEMAP_STYLE,
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  applyDebugBasemapVisibility,
} from '../debug/lib/debugMapBasemap'

export type MapPanelProps = {
  className?: string
  onMapReady?: (map: MapLibreMap) => void
}

export function MapPanel({ className = '', onMapReady }: MapPanelProps) {
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
      style: DEBUG_BASEMAP_STYLE,
      center: DEFAULT_MAP_CENTER,
      zoom: DEFAULT_MAP_ZOOM,
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
        applyDebugBasemapVisibility(map, basemapModeRef.current)
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
    applyDebugBasemapVisibility(map, basemapMode)
  }, [mapReady, basemapMode])

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
