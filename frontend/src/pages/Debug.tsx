import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { DebugHighwayList, wayIdFromProps } from '../components/DebugHighwayList'
import { MapPanel } from '../components/MapPanel'
import { apiUrl } from '../lib/api'
import {
  DEBUG_HIGHWAY_VALUES,
  defaultDebugHighwaySelection,
  type DebugHighwayValue,
} from '../lib/debugHighways'

/** テキスト・一覧とも「まだ取得していない」状態の表示 */
const DEBUG_EMPTY_PLACEHOLDER = '（未取得）'

type PanelMode = 'text' | 'ui'

function fitMapToLineString(map: MapLibreMap, coords: [number, number][]) {
  if (coords.length === 0) return
  const bounds = new maplibregl.LngLatBounds(coords[0], coords[0])
  for (let i = 1; i < coords.length; i++) {
    bounds.extend(coords[i] as [number, number])
  }
  map.fitBounds(bounds, { padding: 56, maxZoom: 18, duration: 380 })
}

/**
 * デバッグ用サンドボックス。必要に応じて丸ごと差し替えてよい。
 * 現在: Overpass 経由の highway タグ付き way を最大100件、テキスト/UI 一覧 + 地図ライン表示。
 */
export function DebugPage() {
  const mapRef = useRef<MapLibreMap | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [textDump, setTextDump] = useState('')
  const [geojson, setGeojson] = useState<GeoJSON.FeatureCollection | null>(null)
  const [panelMode, setPanelMode] = useState<PanelMode>('ui')
  const [selectedWayId, setSelectedWayId] = useState<number | string | null>(null)
  const [highwayInclude, setHighwayInclude] = useState(defaultDebugHighwaySelection)
  const [highwayFilterOpen, setHighwayFilterOpen] = useState(false)

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

  const selectedHighwayTypes = DEBUG_HIGHWAY_VALUES.filter((h) => highwayInclude[h])
  const canFetchHighways = selectedHighwayTypes.length > 0

  const setHighwayChecked = (value: DebugHighwayValue, checked: boolean) => {
    setHighwayInclude((prev) => ({ ...prev, [value]: checked }))
  }

  const fetchHighways = async () => {
    const map = mapRef.current
    if (!map) {
      setError('地図の準備ができていません。')
      return
    }
    if (!canFetchHighways) {
      setError('取得する highway を1つ以上選んでください。')
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
      for (const h of selectedHighwayTypes) {
        q.append('highway', h)
      }
      const res = await fetch(apiUrl(`/api/debug/highways?${q.toString()}`))
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

  const emptyPlaceholder = (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <p className="px-3 py-6 text-center text-sm text-stone-500">{DEBUG_EMPTY_PLACEHOLDER}</p>
    </div>
  )

  const fetchedWayCount = geojson != null ? features.length : null

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <aside className="flex min-h-0 w-full flex-1 flex-col gap-4.5 overflow-hidden p-5 pb-4 lg:max-w-sm lg:h-full lg:flex-none lg:min-h-0 lg:overflow-visible lg:shrink-0 lg:py-5 lg:pl-5 lg:pr-0">
        <div className="shrink-0 flex flex-col gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight text-stone-800">デバッグページ</h1>
          <div
            className="rounded-xl border border-stone-200/90 bg-white/80 p-3 shadow-sm"
            role="group"
            aria-labelledby="debug-highway-filter-heading"
          >
            <button
              type="button"
              id="debug-highway-filter-heading"
              onClick={() => setHighwayFilterOpen((o) => !o)}
              aria-expanded={highwayFilterOpen}
              className={[
                'flex w-full cursor-pointer items-center gap-1.5 rounded-md text-left text-xs font-medium leading-snug text-stone-600 outline-none ring-[#4a6f8a]/30 hover:text-stone-800 focus-visible:ring-2',
                highwayFilterOpen ? 'mb-2.5' : 'mb-0',
              ].join(' ')}
            >
              <svg
                className={[
                  'size-4 shrink-0 text-stone-500 transition-transform duration-200 ease-out',
                  highwayFilterOpen ? 'rotate-90' : 'rotate-0',
                ].join(' ')}
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden
              >
                <path
                  fillRule="evenodd"
                  d="M7.22 4.22a.75.75 0 0 1 1.06 0l5.25 5.25a.75.75 0 0 1 0 1.06l-5.25 5.25a.75.75 0 1 1-1.06-1.06L11.94 10 7.22 5.28a.75.75 0 0 1 0-1.06Z"
                  clipRule="evenodd"
                />
              </svg>
              <span>含める highway=*</span>
            </button>
            {highwayFilterOpen ? (
              <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {DEBUG_HIGHWAY_VALUES.map((value) => (
                  <li key={value}>
                    <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                      <input
                        type="checkbox"
                        className="size-4 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
                        checked={highwayInclude[value]}
                        onChange={(e) => setHighwayChecked(value, e.target.checked)}
                      />
                      <span className="font-mono text-[13px]">{value}</span>
                    </label>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <button
            type="button"
            disabled={loading || !canFetchHighways}
            className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-50"
            onClick={fetchHighways}
          >
            {loading ? '取得中…' : '表示範囲で highway を取得（最大100）'}
          </button>
        </div>

        <p className="shrink-0 text-xs leading-relaxed text-stone-600">
          範囲が広いと Overpass が重くなります。ズームしてから取得してください。{' '}
          <code className="rounded bg-stone-200/80 px-1">VITE_API_BASE</code> を frontend に設定してください。
        </p>

        {error ? <p className="shrink-0 text-sm text-red-700">{error}</p> : null}

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <div
            className="inline-flex w-fit shrink-0 self-start rounded-xl border border-dashed border-stone-400 bg-white p-0.5 shadow-sm"
            role="group"
            aria-label="左パネル表示モード"
          >
            <button
              type="button"
              onClick={() => setPanelMode('text')}
              className={[
                'rounded-[10px] px-3 py-2 text-sm font-medium transition-colors',
                panelMode === 'text'
                  ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                  : 'text-stone-600 hover:text-stone-800',
              ].join(' ')}
            >
              テキスト
            </button>
            <button
              type="button"
              onClick={() => setPanelMode('ui')}
              className={[
                'rounded-[10px] px-3 py-2 text-sm font-medium transition-colors',
                panelMode === 'ui'
                  ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                  : 'text-stone-600 hover:text-stone-800',
              ].join(' ')}
            >
              一覧
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
            {fetchedWayCount != null ? (
              <p className="shrink-0 text-[11px] leading-none text-stone-400 tabular-nums">
                取得した道: {fetchedWayCount} 件
              </p>
            ) : null}

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] lg:min-h-[200px]">
              {panelMode === 'text' ? (
                textDump ? (
                  <pre className="min-h-0 flex-1 overflow-auto p-3 text-[11px] leading-snug text-stone-800">
                    {textDump}
                  </pre>
                ) : (
                  emptyPlaceholder
                )
              ) : geojson ? (
                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                  <DebugHighwayList
                    features={features}
                    selectedWayId={selectedWayId}
                    onSelectWay={handleSelectWay}
                  />
                </div>
              ) : (
                emptyPlaceholder
              )}
            </div>
          </div>
          
        </div>

        <Link
          to="/"
          className="mt-auto shrink-0 text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline"
        >
          ← アプリに戻る
        </Link>
      </aside>

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
