import maplibregl, { type LngLatBoundsLike, type Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useRef } from 'react'

export type MapPanelProps = {
  className?: string
  overlayGeoJson?: GeoJSON.FeatureCollection | null
  overlayLineColor?: string
  onMapReady?: (map: MapLibreMap) => void
}

const DEFAULT_CENTER: [number, number] = [139.7671, 35.6812]
const DEFAULT_ZOOM = 12

const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  },
  layers: [
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      minzoom: 0,
      maxzoom: 19,
    },
  ],
}

function applyOverlay(
  map: MapLibreMap,
  overlayGeoJson: GeoJSON.FeatureCollection | null | undefined,
  overlayLineColor: string,
) {
  const srcId = 'debug-overlay'
  const layerId = 'debug-overlay-line'

  if (map.getLayer(layerId)) map.removeLayer(layerId)
  if (map.getSource(srcId)) map.removeSource(srcId)

  if (!overlayGeoJson || overlayGeoJson.features.length === 0) return

  map.addSource(srcId, {
    type: 'geojson',
    data: overlayGeoJson,
  })
  map.addLayer({
    id: layerId,
    type: 'line',
    source: srcId,
    paint: {
      'line-color': overlayLineColor,
      'line-width': 2,
      'line-opacity': 0.85,
    },
  })

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

export function MapPanel({
  className = '',
  overlayGeoJson,
  overlayLineColor = '#c45c3e',
  onMapReady,
}: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const overlayRef = useRef(overlayGeoJson)
  const colorRef = useRef(overlayLineColor)

  useEffect(() => {
    overlayRef.current = overlayGeoJson
    colorRef.current = overlayLineColor
  }, [overlayGeoJson, overlayLineColor])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const map = new maplibregl.Map({
      container: el,
      style: OSM_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    const resize = () => map.resize()
    window.addEventListener('resize', resize)

    map.once('load', () => {
      onMapReady?.(map)
      applyOverlay(map, overlayRef.current, colorRef.current)
    })

    return () => {
      window.removeEventListener('resize', resize)
      map.remove()
      mapRef.current = null
    }
  }, [onMapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map?.loaded()) return
    applyOverlay(map, overlayGeoJson, overlayLineColor)
  }, [overlayGeoJson, overlayLineColor])

  return <div ref={containerRef} className={className} />
}
