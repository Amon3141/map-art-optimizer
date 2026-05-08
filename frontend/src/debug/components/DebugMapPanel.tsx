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
import { HIGHLIGHT_OSM_MERGE, HIGHLIGHT_SNAP_MERGE } from '../lib/debugHighlightColors'

const OSM_SRC = 'debug-osm-overlay'
const OSM_LINE = 'debug-osm-overlay-line'
const G_EDGES_SRC = 'debug-graph-edges'
const G_EDGES_LINE = 'debug-graph-edges-line'
const G_DEDUPE_RM_EDGES_SRC = 'debug-graph-dedupe-rm-edges'
const G_DEDUPE_RM_EDGES = 'debug-graph-dedupe-rm-edges-line'
const G_DEDUPE_RM_VERTS_SRC = 'debug-graph-dedupe-rm-verts'
const G_DEDUPE_RM_VERTS = 'debug-graph-dedupe-rm-verts-circle'
const G_NODES_SRC = 'debug-graph-nodes'
const G_NODES_LAYER = 'debug-graph-nodes-circle'
const G_PILE_LABEL = 'debug-graph-pile-label'
const G_JUNCTION_LABEL = 'debug-graph-junction-label'

/** visibility 切り替え・削除用（スタイル内の上→下の順と一致させる） */
const GRAPH_LAYER_IDS = [
  G_JUNCTION_LABEL,
  G_PILE_LABEL,
  G_NODES_LAYER,
  G_DEDUPE_RM_VERTS,
  G_DEDUPE_RM_EDGES,
  G_EDGES_LINE,
] as const

export type DebugMapViewMode = 'osm' | 'graph'

export type DebugGraphGeoJson = {
  nodes: GeoJSON.FeatureCollection
  edges: GeoJSON.FeatureCollection
  dedupe_removed_edges?: GeoJSON.FeatureCollection
  dedupe_removed_vertices?: GeoJSON.FeatureCollection
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
  onMapReady?: (map: MapLibreMap) => void
}

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

function removeOsmOverlay(map: MapLibreMap) {
  if (map.getLayer(OSM_LINE)) map.removeLayer(OSM_LINE)
  if (map.getSource(OSM_SRC)) map.removeSource(OSM_SRC)
}

function removeGraphLayers(map: MapLibreMap) {
  for (const lid of GRAPH_LAYER_IDS) {
    if (map.getLayer(lid)) map.removeLayer(lid)
  }
  if (map.getSource(G_NODES_SRC)) map.removeSource(G_NODES_SRC)
  if (map.getSource(G_EDGES_SRC)) map.removeSource(G_EDGES_SRC)
  if (map.getSource(G_DEDUPE_RM_VERTS_SRC)) map.removeSource(G_DEDUPE_RM_VERTS_SRC)
  if (map.getSource(G_DEDUPE_RM_EDGES_SRC)) map.removeSource(G_DEDUPE_RM_EDGES_SRC)
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
  onMapReady,
}: DebugMapPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const lastGraphFitTriggerRef = useRef<number>(-1)
  const popupRef = useRef<Popup | null>(null)
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

    const data = injectSelected(g, overlaySelectedId)
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

    const insertBeforeOsm = map.getLayer(OSM_LINE) ? OSM_LINE : undefined
    const dre = gg.dedupe_removed_edges
    const drv = gg.dedupe_removed_vertices
    if (dre && dre.features.length > 0) {
      map.addSource(G_DEDUPE_RM_EDGES_SRC, { type: 'geojson', data: dre })
      map.addLayer(
        {
          id: G_DEDUPE_RM_EDGES,
          type: 'line',
          source: G_DEDUPE_RM_EDGES_SRC,
          paint: {
            'line-color': '#78716c',
            'line-width': 2,
            'line-opacity': 0.82,
            'line-dasharray': [2, 2],
          },
        },
        insertBeforeOsm,
      )
    }
    if (drv && drv.features.length > 0) {
      map.addSource(G_DEDUPE_RM_VERTS_SRC, { type: 'geojson', data: drv })
      map.addLayer(
        {
          id: G_DEDUPE_RM_VERTS,
          type: 'circle',
          source: G_DEDUPE_RM_VERTS_SRC,
          paint: {
            'circle-radius': 5,
            'circle-color': '#57534e',
            'circle-opacity': 0.5,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#faf8f4',
            'circle-stroke-opacity': 0.45,
          },
        },
        insertBeforeOsm,
      )
    }

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
            '#e11d48',
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
  }, [mapReady, graphGeoJson, graphFitTrigger])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map) return

    const osmVis = viewMode === 'osm' ? 'visible' : 'none'
    const gVis = viewMode === 'graph' ? 'visible' : 'none'

    if (map.getLayer(OSM_LINE)) {
      map.setLayoutProperty(OSM_LINE, 'visibility', osmVis)
    }
    for (const lid of GRAPH_LAYER_IDS) {
      if (map.getLayer(lid)) {
        map.setLayoutProperty(lid, 'visibility', gVis)
      }
    }
  }, [mapReady, viewMode])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map || viewMode !== 'osm') {
      popupRef.current?.remove()
      return
    }
    if (!map.getLayer(OSM_LINE)) return

    const popup = new maplibregl.Popup({
      closeButton: true,
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

    map.on('mousemove', OSM_LINE, onMove)
    map.on('mouseleave', OSM_LINE, onLeave)
    map.on('click', OSM_LINE, onClick)

    return () => {
      map.off('mousemove', OSM_LINE, onMove)
      map.off('mouseleave', OSM_LINE, onLeave)
      map.off('click', OSM_LINE, onClick)
      popup.remove()
    }
  }, [mapReady, viewMode, osmGeoJson])

  return (
    <div className={`relative min-h-0 w-full min-w-0 flex-1 ${className}`}>
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
      <div className="pointer-events-none absolute left-3 top-3 z-10 sm:left-4 sm:top-4">
        <BasemapSelector value={basemapMode} onChange={setBasemapMode} />
      </div>
    </div>
  )
}
