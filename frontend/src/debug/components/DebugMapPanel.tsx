import maplibregl, {
  type LngLatBoundsLike,
  type Map as MapLibreMap,
  type Popup,
} from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { BasemapSelector, type BasemapMode } from '../../components/BasemapSelector'
import {
  DEBUG_BASEMAP_STYLE,
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  applyDebugBasemapVisibility,
} from '../lib/debugMapBasemap'
import { HIGHLIGHT_OSM_MERGE, HIGHLIGHT_SNAP_MERGE, HIGHLIGHT_SYNTHETIC } from '../lib/debugHighlightColors'
import { injectOsmOverlaySelection } from '../lib/debugOsmOverlay'

const OSM_SRC = 'debug-osm-overlay'
const OSM_LINE = 'debug-osm-overlay-line'
const OSM_LINE_HIT = 'debug-osm-overlay-line-hit'
const G_EDGES_SRC = 'debug-graph-edges'
const G_EDGES_LINE = 'debug-graph-edges-line'
const G_NODES_SRC = 'debug-graph-nodes'
const G_NODES_LAYER = 'debug-graph-nodes-circle'
const G_PILE_LABEL = 'debug-graph-pile-label'
const G_JUNCTION_LABEL = 'debug-graph-junction-label'

const ROUTE_SRC = 'debug-route-overlay'
const ROUTE_LINE = 'debug-route-overlay-line'

/** マップ上テキストを表示する最小ズーム */
const GRAPH_NODE_LABELS_MIN_ZOOM = 17

/** グラフのノード系レイヤ（visibility をエッジと独立に切り替え） */
const GRAPH_NODE_LAYER_IDS = [G_JUNCTION_LABEL, G_PILE_LABEL, G_NODES_LAYER] as const

/** visibility 切り替え・削除用（スタイル内の上→下の順と一致させる） */
const GRAPH_LAYER_IDS = [...GRAPH_NODE_LAYER_IDS, G_EDGES_LINE] as const

export type DebugMapViewMode = 'osm' | 'graph'

export type DebugGraphGeoJson = {
  nodes: GeoJSON.FeatureCollection
  edges: GeoJSON.FeatureCollection
}

export type DebugMapPanelProps = {
  className?: string
  viewMode: DebugMapViewMode
  osmGeoJson: GeoJSON.FeatureCollection | null
  graphGeoJson: DebugGraphGeoJson | null
  overlaySelectedId?: number | string | null
  overlayLineColor?: string
  overlayHighlightColor?: string
  fitOsmOverlayToData?: boolean
  /** 値が変わったときだけグラフ表示に合わせてフィット（オプション変更のみの更新では増やさない） */
  graphFitTrigger?: number
  /** 最適化ルートなど（グラフ・OSM の上に描画） */
  routeOverlay?: GeoJSON.FeatureCollection | null
  routeLineColor?: string
  onMapReady?: (map: MapLibreMap) => void
}

function removeOsmOverlay(map: MapLibreMap) {
  if (map.getLayer(OSM_LINE_HIT)) map.removeLayer(OSM_LINE_HIT)
  if (map.getLayer(OSM_LINE)) map.removeLayer(OSM_LINE)
  if (map.getSource(OSM_SRC)) map.removeSource(OSM_SRC)
}

function removeGraphLayers(map: MapLibreMap) {
  for (const lid of GRAPH_LAYER_IDS) {
    if (map.getLayer(lid)) map.removeLayer(lid)
  }
  if (map.getSource(G_NODES_SRC)) map.removeSource(G_NODES_SRC)
  if (map.getSource(G_EDGES_SRC)) map.removeSource(G_EDGES_SRC)
}

function removeRouteOverlay(map: MapLibreMap) {
  if (map.getLayer(ROUTE_LINE)) map.removeLayer(ROUTE_LINE)
  if (map.getSource(ROUTE_SRC)) map.removeSource(ROUTE_SRC)
}

function applyGraphLayerVisibility(
  map: MapLibreMap,
  viewMode: DebugMapViewMode,
  showGraphNodes: boolean,
) {
  const graphMode = viewMode === 'graph'
  const edgeVis = graphMode ? 'visible' : 'none'
  const nodeVis = graphMode && showGraphNodes ? 'visible' : 'none'
  if (map.getLayer(G_EDGES_LINE)) {
    map.setLayoutProperty(G_EDGES_LINE, 'visibility', edgeVis)
  }
  for (const lid of GRAPH_NODE_LAYER_IDS) {
    if (map.getLayer(lid)) {
      map.setLayoutProperty(lid, 'visibility', nodeVis)
    }
  }
}

function fitCollectionBounds(map: MapLibreMap, ...collections: GeoJSON.FeatureCollection[]) {
  const bounds = new maplibregl.LngLatBounds()
  let any = false
  for (const coll of collections) {
    for (const f of coll.features) {
      const g = f.geometry
      if (!g) continue
      if (g.type === 'LineString') {
        for (const c of g.coordinates as [number, number][]) {
          bounds.extend(c)
          any = true
        }
      } else if (g.type === 'Point') {
        bounds.extend(g.coordinates as [number, number])
        any = true
      }
    }
  }
  if (any) {
    map.fitBounds(bounds as LngLatBoundsLike, { padding: 48, maxZoom: 17, duration: 0 })
  }
}

function osmPopupHtml(props: Record<string, unknown>): string {
  const wid = props.osm_way_id
  const hw = props.highway
  const epA = props.osm_endpoint_node_a
  const epB = props.osm_endpoint_node_b
  const tags = Object.entries(props)
    .filter(
      ([k]) =>
        !k.startsWith('_') &&
        k !== 'osm_node_ids' &&
        k !== 'geometry' &&
        typeof k === 'string',
    )
    .slice(0, 14)
    .map(([k, v]) => `<div><span class="k">${escapeHtml(k)}</span>: ${escapeHtml(String(v))}</div>`)
    .join('')
  return `
    <div class="dbg-pop">
      <div class="t">way #${escapeHtml(String(wid ?? '?'))}</div>
      ${hw != null ? `<div class="hw">${escapeHtml(String(hw))}</div>` : ''}
      <div class="ep">端点 OSM node: <b>${escapeHtml(String(epA ?? '?'))}</b> — <b>${escapeHtml(String(epB ?? '?'))}</b></div>
      <div class="tags">${tags}</div>
    </div>
  `
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function DebugMapPanel({
  className = '',
  viewMode,
  osmGeoJson,
  graphGeoJson,
  overlaySelectedId = null,
  overlayLineColor = '#c45c3e',
  overlayHighlightColor = '#3b9ede',
  fitOsmOverlayToData = true,
  graphFitTrigger = 0,
  routeOverlay = null,
  routeLineColor = '#b45309',
  onMapReady,
}: DebugMapPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const lastGraphFitTriggerRef = useRef<number>(-1)
  const popupRef = useRef<Popup | null>(null)
  const onMapReadyRef = useRef(onMapReady)
  const basemapModeRef = useRef<BasemapMode>('normal')
  const viewModeRef = useRef<DebugMapViewMode>('osm')
  const showGraphNodesRef = useRef(true)
  const [mapReady, setMapReady] = useState(false)
  const [basemapMode, setBasemapMode] = useState<BasemapMode>('normal')
  const [showGraphNodes, setShowGraphNodes] = useState(true)

  onMapReadyRef.current = onMapReady
  basemapModeRef.current = basemapMode
  viewModeRef.current = viewMode
  showGraphNodesRef.current = showGraphNodes

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
      })
      onMapReadyRef.current?.(map)
      setMapReady(true)
    })

    return () => {
      cancelled = true
      ro.disconnect()
      window.removeEventListener('resize', resize)
      popupRef.current?.remove()
      popupRef.current = null
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

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    const g = osmGeoJson
    if (!g || g.features.length === 0) {
      removeOsmOverlay(map)
      return
    }

    const data = injectOsmOverlaySelection(g, overlaySelectedId)
    const lineColor: maplibregl.ExpressionSpecification = [
      'case',
      ['==', ['get', '_selected'], 1],
      overlayHighlightColor,
      overlayLineColor,
    ]

    const src = map.getSource(OSM_SRC) as maplibregl.GeoJSONSource | undefined
    if (!src) {
      map.addSource(OSM_SRC, { type: 'geojson', data })
      map.addLayer({
        id: OSM_LINE,
        type: 'line',
        source: OSM_SRC,
        paint: { 'line-color': lineColor, 'line-width': 4, 'line-opacity': 0.88 },
      })
      map.addLayer({
        id: OSM_LINE_HIT,
        type: 'line',
        source: OSM_SRC,
        paint: { 'line-width': 16, 'line-opacity': 0 },
      })
      if (fitOsmOverlayToData) fitCollectionBounds(map, g)
    } else {
      src.setData(data)
      map.setPaintProperty(OSM_LINE, 'line-color', lineColor)
      if (fitOsmOverlayToData) fitCollectionBounds(map, g)
    }
  }, [
    mapReady,
    osmGeoJson,
    overlaySelectedId,
    overlayLineColor,
    overlayHighlightColor,
    fitOsmOverlayToData,
  ])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    removeGraphLayers(map)
    const gg = graphGeoJson
    if (!gg || (gg.edges.features.length === 0 && gg.nodes.features.length === 0)) {
      return
    }

    map.addSource(G_EDGES_SRC, { type: 'geojson', data: gg.edges })
    const graphBefore = map.getLayer(OSM_LINE) ? OSM_LINE : undefined
    map.addLayer(
      {
        id: G_EDGES_LINE,
        type: 'line',
        source: G_EDGES_SRC,
        paint: {
          'line-color': '#0f766e',
          'line-width': 2.5,
          'line-opacity': 0.92,
        },
      },
      graphBefore,
    )

    map.addSource(G_NODES_SRC, { type: 'geojson', data: gg.nodes })

    // エッジは OSM の手前（下）へ。ノード／ラベルはスタイル末尾へ載せて線より確実に手前に描画する
    map.addLayer(
      {
        id: G_NODES_LAYER,
        type: 'circle',
        source: G_NODES_SRC,
        paint: {
          'circle-radius': [
            'case',
            ['==', ['get', 'vertex_role'], 'inline'],
            4.6,
            ['==', ['get', 'synthetic'], true],
            6.2,
            6.6,
          ],
          'circle-color': [
            'case',
            ['==', ['get', 'highlight_snap_merge'], true],
            HIGHLIGHT_SNAP_MERGE,
            ['==', ['get', 'highlight_osm_merge'], true],
            HIGHLIGHT_OSM_MERGE,
            ['==', ['get', 'synthetic'], true],
            HIGHLIGHT_SYNTHETIC,
            ['==', ['get', 'vertex_role'], 'inline'],
            '#64748b',
            '#2563eb',
          ],
          'circle-stroke-width': 1.2,
          'circle-stroke-color': '#faf8f4',
        },
      },
    )
    map.addLayer(
      {
        id: G_PILE_LABEL,
        type: 'symbol',
        source: G_NODES_SRC,
        minzoom: GRAPH_NODE_LABELS_MIN_ZOOM,
        filter: ['>', ['get', 'pile_count'], 1],
        layout: {
          'text-field': ['to-string', ['get', 'pile_count']],
          'text-size': 11,
          'text-offset': [0, -1.35],
          'text-anchor': 'bottom',
          'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
        },
        paint: {
          'text-color': '#0f172a',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2,
        },
      },
    )
    map.addLayer(
      {
        id: G_JUNCTION_LABEL,
        type: 'symbol',
        source: G_NODES_SRC,
        minzoom: GRAPH_NODE_LABELS_MIN_ZOOM,
        filter: ['==', ['get', 'vertex_role'], 'junction'],
        layout: {
          'text-field': ['get', 'internal_node_id'],
          'text-size': 9,
          'text-offset': [0, 1.25],
          'text-anchor': 'top',
          'text-max-width': 14,
          'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'],
        },
        paint: {
          'text-color': '#334155',
          'text-halo-color': '#faf8f4',
          'text-halo-width': 1.2,
        },
      },
    )

    if (graphFitTrigger !== lastGraphFitTriggerRef.current) {
      fitCollectionBounds(map, gg.edges, gg.nodes)
      lastGraphFitTriggerRef.current = graphFitTrigger
    }

    applyGraphLayerVisibility(map, viewModeRef.current, showGraphNodesRef.current)
  }, [mapReady, graphGeoJson, graphFitTrigger])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    removeRouteOverlay(map)
    const ro = routeOverlay
    if (!ro || ro.features.length === 0) return
    const hasLine = ro.features.some(
      (f) => f.geometry?.type === 'LineString' && (f.geometry.coordinates?.length ?? 0) >= 2,
    )
    if (!hasLine) return

    map.addSource(ROUTE_SRC, { type: 'geojson', data: ro })
    map.addLayer({
      id: ROUTE_LINE,
      type: 'line',
      source: ROUTE_SRC,
      paint: {
        'line-color': routeLineColor,
        'line-width': 5,
        'line-opacity': 0.92,
      },
    })
  }, [mapReady, routeOverlay, routeLineColor, graphGeoJson])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    const osmVis = viewMode === 'osm' ? 'visible' : 'none'

    if (map.getLayer(OSM_LINE)) {
      map.setLayoutProperty(OSM_LINE, 'visibility', osmVis)
    }
    if (map.getLayer(OSM_LINE_HIT)) {
      map.setLayoutProperty(OSM_LINE_HIT, 'visibility', osmVis)
    }
    applyGraphLayerVisibility(map, viewMode, showGraphNodes)
  }, [mapReady, viewMode, showGraphNodes])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map || viewMode !== 'osm') {
      popupRef.current?.remove()
      return
    }
    if (!map.getLayer(OSM_LINE_HIT)) return

    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      maxWidth: '320px',
      className: 'debug-osm-popup',
    })
    popupRef.current = popup

    const onMove = (
      e: maplibregl.MapMouseEvent & {
        features?: maplibregl.MapGeoJSONFeature[]
      },
    ) => {
      const f = e.features?.[0]
      if (!f?.properties) return
      map.getCanvas().style.cursor = 'pointer'
      const p = f.properties as Record<string, unknown>
      popup.setLngLat(e.lngLat).setHTML(osmPopupHtml(p)).addTo(map)
    }
    const onLeave = () => {
      map.getCanvas().style.cursor = ''
      popup.remove()
    }
    const onClick = (
      e: maplibregl.MapMouseEvent & {
        features?: maplibregl.MapGeoJSONFeature[]
      },
    ) => {
      const f = e.features?.[0]
      if (!f?.properties) return
      const p = f.properties as Record<string, unknown>
      popup.setLngLat(e.lngLat).setHTML(osmPopupHtml(p)).addTo(map)
    }

    map.on('mousemove', OSM_LINE_HIT, onMove)
    map.on('mouseleave', OSM_LINE_HIT, onLeave)
    map.on('click', OSM_LINE_HIT, onClick)

    return () => {
      map.off('mousemove', OSM_LINE_HIT, onMove)
      map.off('mouseleave', OSM_LINE_HIT, onLeave)
      map.off('click', OSM_LINE_HIT, onClick)
      popup.remove()
    }
  }, [mapReady, viewMode, osmGeoJson])

  return (
    <div className={`flex min-h-0 w-full min-w-0 flex-1 flex-col ${className}`}>
      <div className="relative min-h-0 w-full min-w-0 flex-1">
        <style>{`
          .debug-osm-popup .maplibregl-popup-content {
            padding: 10px 12px;
            border-radius: 10px;
            font-size: 12px;
            max-height: 260px;
            overflow-y: auto;
          }
          .dbg-pop .t { font-weight: 600; color: #292524; margin-bottom: 4px; }
          .dbg-pop .hw { font-family: ui-monospace, monospace; font-size: 11px; color: #57534e; margin-bottom: 6px; }
          .dbg-pop .ep { font-size: 11px; color: #44403c; margin-bottom: 8px; line-height: 1.4; }
          .dbg-pop .tags { font-size: 10px; color: #57534e; font-family: ui-monospace, monospace; }
          .dbg-pop .k { color: #78716c; }
        `}</style>
        <div ref={containerRef} className="absolute inset-0" />
        <div
          className="pointer-events-none absolute inset-0 z-1 shadow-[inset_0_4px_40px_0_rgb(62_36_30/0.095),inset_0_0_280px_0_rgb(48_28_24/0.115)]"
          aria-hidden
        />
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex max-w-[min(100%,calc(100vw-1.5rem))] flex-wrap items-stretch gap-3 sm:left-4 sm:top-4">
          <div className="pointer-events-auto shrink-0">
            <BasemapSelector value={basemapMode} onChange={setBasemapMode} />
          </div>
          {viewMode === 'graph' ? (
            <div
              className="pointer-events-auto inline-flex w-fit shrink-0 flex-nowrap items-stretch gap-0 rounded-full border border-dashed border-stone-400 bg-[#fdfbf7]/95 p-0.5 shadow-sm backdrop-blur-[2px]"
              role="radiogroup"
              aria-label="グラフノードの表示"
            >
              <button
                type="button"
                role="radio"
                aria-checked={!showGraphNodes}
                onClick={() => setShowGraphNodes(false)}
                className={[
                  'min-w-0 shrink rounded-l-full px-2.5 py-2 text-xs font-medium transition-colors sm:px-3 sm:text-sm',
                  !showGraphNodes
                    ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner ring-1 ring-stone-200/80'
                    : 'text-stone-600 hover:border-[#4a6f8a]/30 hover:bg-white/80 hover:text-stone-800',
                ].join(' ')}
              >
                ノードなし
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={showGraphNodes}
                onClick={() => setShowGraphNodes(true)}
                className={[
                  'min-w-0 shrink rounded-r-full px-2.5 py-2 text-xs font-medium transition-colors sm:px-3 sm:text-sm',
                  showGraphNodes
                    ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner ring-1 ring-stone-200/80'
                    : 'text-stone-600 hover:border-[#4a6f8a]/30 hover:bg-white/80 hover:text-stone-800',
                ].join(' ')}
              >
                ノードあり
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
