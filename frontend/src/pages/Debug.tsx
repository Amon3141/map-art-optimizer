import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DebugSidebar, type DebugPanelMode } from '../debug/components/DebugSidebar'
import { DebugMapPanel, type DebugMapViewMode } from '../debug/components/DebugMapPanel'
import { fitMapToLineString } from '../debug/lib/fitMapToWay'
import {
  defaultGraphBuildOptions,
  type GraphBuildOptionsPayload,
  type GraphPreviewResponse,
} from '../debug/lib/graphPreview'
import { wayIdFromProps } from '../debug/components/DebugWayList'
import { apiUrl } from '../lib/api'
import {
  defaultDebugHighwayIncludeSelection,
  filterFeatureCollectionByIncludedHighways,
  type DebugHighwayIncludeSelection,
  type DebugHighwayTag,
} from '../debug/lib/debugHighwayInclude'

/** デバッグ用: Overpass → OSM GeoJSON → 平面グラフの可視化 */
export function DebugPage() {
  const mapRef = useRef<MapLibreMap | null>(null)
  const graphFetchGen = useRef(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [textDump, setTextDump] = useState('')
  const [waysFcRaw, setWaysFcRaw] = useState<GeoJSON.FeatureCollection | null>(null)
  const [highwayInclude, setHighwayInclude] = useState<DebugHighwayIncludeSelection>(() =>
    defaultDebugHighwayIncludeSelection(),
  )
  const [panelMode, setPanelMode] = useState<DebugPanelMode>('ui')
  const [selectedWayId, setSelectedWayId] = useState<number | string | null>(null)
  const [roadFilterOpen, setRoadFilterOpen] = useState(false)
  const [mapViewMode, setMapViewMode] = useState<DebugMapViewMode>('osm')
  const [graphOptions, setGraphOptions] = useState<GraphBuildOptionsPayload>(() =>
    defaultGraphBuildOptions(),
  )
  const [graphPreview, setGraphPreview] = useState<GraphPreviewResponse | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphError, setGraphError] = useState<string | null>(null)
  const [graphFitTrigger, setGraphFitTrigger] = useState(0)
  const prevMapViewModeRef = useRef<DebugMapViewMode>(mapViewMode)

  const onMapReady = useCallback((map: MapLibreMap) => {
    mapRef.current = map
  }, [])

  const geojson = useMemo(() => {
    if (!waysFcRaw) return null
    return filterFeatureCollectionByIncludedHighways(waysFcRaw, highwayInclude)
  }, [waysFcRaw, highwayInclude])

  const features = useMemo(() => geojson?.features ?? [], [geojson])

  const handleSelectWay = useCallback(
    (id: number | string | null) => {
      setSelectedWayId(id)
      if (id == null) return
      const map = mapRef.current
      if (!map?.loaded()) return
      const feat = features.find((f) => {
        if (f.geometry.type !== 'LineString') return false
        const pid = wayIdFromProps(f.properties)
        return pid != null && String(pid) === String(id)
      })
      if (!feat || feat.geometry.type !== 'LineString') return
      fitMapToLineString(map, feat.geometry.coordinates as [number, number][])
    },
    [features],
  )

  const fetchGraphPreview = useCallback(
    async (signal?: AbortSignal) => {
      const map = mapRef.current
      if (!map || !geojson?.features?.length) return
      const gen = ++graphFetchGen.current
      setGraphLoading(true)
      setGraphError(null)
      try {
        const b = map.getBounds()
        const body = {
          geojson,
          bbox: {
            min_lon: b.getWest(),
            min_lat: b.getSouth(),
            max_lon: b.getEast(),
            max_lat: b.getNorth(),
          },
          options: graphOptions,
        }
        const res = await fetch(apiUrl('/api/debug/graph-preview'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal,
        })
        if (!res.ok) {
          const t = await res.text()
          throw new Error(t || res.statusText)
        }
        const data = (await res.json()) as GraphPreviewResponse
        if (gen !== graphFetchGen.current) return
        setGraphPreview({
          ...data,
          step_metrics: data.step_metrics ?? {},
        })
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return
        if (gen !== graphFetchGen.current) return
        setGraphError(e instanceof Error ? e.message : String(e))
      } finally {
        if (gen === graphFetchGen.current) setGraphLoading(false)
      }
    },
    [geojson, graphOptions],
  )

  useEffect(() => {
    if (mapViewMode !== 'graph' || !geojson?.features?.length) return
    const ac = new AbortController()
    const tid = window.setTimeout(() => {
      void fetchGraphPreview(ac.signal)
    }, 380)
    return () => {
      window.clearTimeout(tid)
      ac.abort()
    }
  }, [mapViewMode, geojson, graphOptions, fetchGraphPreview])

  useEffect(() => {
    if (mapViewMode === 'graph' && prevMapViewModeRef.current !== 'graph') {
      setGraphFitTrigger((n) => n + 1)
    }
    prevMapViewModeRef.current = mapViewMode
  }, [mapViewMode])

  const fetchWays = async () => {
    const map = mapRef.current
    if (!map) {
      setError('地図の準備ができていません。')
      return
    }
    const b = map.getBounds()
    const minLon = b.getWest()
    const minLat = b.getSouth()
    const maxLon = b.getEast()
    const maxLat = b.getNorth()

    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({
        min_lat: String(minLat),
        min_lon: String(minLon),
        max_lat: String(maxLat),
        max_lon: String(maxLon),
      })
      const res = await fetch(apiUrl(`/api/debug/ways?${q.toString()}`))
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || res.statusText)
      }
      const data = (await res.json()) as {
        geojson: GeoJSON.FeatureCollection
        raw_preview: string
      }
      setTextDump(data.raw_preview)
      setWaysFcRaw(data.geojson)
      setSelectedWayId(null)
      setGraphPreview(null)
      setGraphError(null)
      setGraphFitTrigger((n) => n + 1)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const onHighwayIncludeChecked = (value: DebugHighwayTag, checked: boolean) => {
    setHighwayInclude((prev) => ({ ...prev, [value]: checked }))
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <DebugSidebar
        loading={loading}
        error={error}
        textDump={textDump}
        geojson={geojson}
        waysFetchedCount={waysFcRaw?.features?.length ?? null}
        highwayInclude={highwayInclude}
        onHighwayIncludeChecked={onHighwayIncludeChecked}
        roadFilterOpen={roadFilterOpen}
        onRoadFilterOpenChange={setRoadFilterOpen}
        panelMode={panelMode}
        onPanelModeChange={setPanelMode}
        selectedWayId={selectedWayId}
        onSelectWay={handleSelectWay}
        onFetchWays={fetchWays}
        mapViewMode={mapViewMode}
        onMapViewModeChange={setMapViewMode}
        graphOptions={graphOptions}
        onGraphOptionsChange={setGraphOptions}
        graphLoading={graphLoading}
        graphError={graphError}
        graphPreview={graphPreview}
      />

      <main className="flex min-h-0 min-w-0 shrink-0 flex-col px-3 pb-3 pt-1.5 max-lg:h-[min(42vh,360px)] max-lg:min-h-[260px] max-lg:flex-none lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] max-lg:min-h-0 lg:min-h-[280px]">
          <DebugMapPanel
            className="min-h-0 w-full flex-1"
            viewMode={mapViewMode}
            osmGeoJson={geojson}
            graphGeoJson={graphPreview?.graph_geojson ?? null}
            overlaySelectedId={selectedWayId}
            fitOsmOverlayToData={false}
            graphFitTrigger={graphFitTrigger}
            onMapReady={onMapReady}
          />
        </div>
      </main>
    </div>
  )
}
