import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useRef, useState } from 'react'
import { DebugSidebar, type DebugPanelMode } from '../debug/components/DebugSidebar'
import { fitMapToLineString } from '../debug/lib/fitMapToWay'
import { wayIdFromProps } from '../debug/components/DebugWayList'
import { MapPanel } from '../components/MapPanel'
import { apiUrl } from '../lib/api'
import {
  DEBUG_ROAD_TYPE_VALUES,
  defaultDebugRoadTypeSelection,
  type DebugRoadType,
} from '../debug/lib/debugRoadTypes'

/**
 * デバッグ用サンドボックス。必要に応じて丸ごと差し替えてよい。
 * 現在: Overpass 経由で道路の way を最大100件、テキスト/UI 一覧 + 地図ライン表示。
 */
export function DebugPage() {
  const mapRef = useRef<MapLibreMap | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [textDump, setTextDump] = useState('')
  const [geojson, setGeojson] = useState<GeoJSON.FeatureCollection | null>(null)
  const [panelMode, setPanelMode] = useState<DebugPanelMode>('ui')
  const [selectedWayId, setSelectedWayId] = useState<number | string | null>(null)
  const [roadTypeInclude, setRoadTypeInclude] = useState(() => defaultDebugRoadTypeSelection())
  const [roadTypeFilterOpen, setRoadTypeFilterOpen] = useState(false)

  const onMapReady = useCallback((map: MapLibreMap) => {
    mapRef.current = map
  }, [])

  const features = geojson?.features ?? []

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

  const selectedRoadTypes = DEBUG_ROAD_TYPE_VALUES.filter((t) => roadTypeInclude[t])
  const canFetchWays = selectedRoadTypes.length > 0

  const fetchWays = async () => {
    const map = mapRef.current
    if (!map) {
      setError('地図の準備ができていません。')
      return
    }
    if (!canFetchWays) {
      setError('取得する道路種別を1つ以上選んでください。')
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
        limit: '100',
      })
      for (const t of selectedRoadTypes) {
        q.append('road_type', t)
      }
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
      setGeojson(data.geojson)
      setSelectedWayId(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const onRoadTypeChecked = (value: DebugRoadType, checked: boolean) => {
    setRoadTypeInclude((prev) => ({ ...prev, [value]: checked }))
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <DebugSidebar
        loading={loading}
        error={error}
        textDump={textDump}
        geojson={geojson}
        panelMode={panelMode}
        onPanelModeChange={setPanelMode}
        selectedWayId={selectedWayId}
        onSelectWay={handleSelectWay}
        roadTypeInclude={roadTypeInclude}
        roadTypeFilterOpen={roadTypeFilterOpen}
        onRoadTypeFilterOpenChange={setRoadTypeFilterOpen}
        onRoadTypeChecked={onRoadTypeChecked}
        canFetchWays={canFetchWays}
        onFetchWays={fetchWays}
      />

      <main className="flex min-h-0 min-w-0 shrink-0 flex-col px-3 pb-3 pt-1.5 max-lg:h-[min(42vh,360px)] max-lg:min-h-[260px] max-lg:flex-none lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] max-lg:min-h-0 lg:min-h-[280px]">
          <MapPanel
            className="min-h-0 w-full flex-1"
            overlayGeoJson={geojson}
            overlaySelectedId={selectedWayId}
            fitOverlayToData={false}
            onMapReady={onMapReady}
          />
        </div>
      </main>
    </div>
  )
}
