import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { MapPanel } from '../components/MapPanel'
import { apiUrl } from '../lib/api'

/**
 * デバッグ用サンドボックス。必要に応じて丸ごと差し替えてよい。
 * 現在: Overpass 経由の highway を最大100件、テキスト先頭 + 地図ライン表示。
 */
export function DebugPage() {
  const mapRef = useRef<MapLibreMap | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [textDump, setTextDump] = useState('')
  const [geojson, setGeojson] = useState<GeoJSON.FeatureCollection | null>(null)

  const onMapReady = useCallback((map: MapLibreMap) => {
    mapRef.current = map
  }, [])

  const fetchHighways = async () => {
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
        limit: '100',
      })
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-col gap-2">
        <Link to="/" className="text-sm font-medium text-[#4a6f8a] hover:underline">
          ← アプリに戻る
        </Link>
        <div className="flex flex-wrap items-center gap-1.5">
          <h1 className="text-lg font-semibold text-stone-800">デバッグ（OSM highway）</h1>
          <button
            type="button"
            disabled={loading}
            className="rounded-lg bg-[#4a6f8a] px-3 py-1.5 text-sm text-white disabled:opacity-50"
            onClick={fetchHighways}
          >
            {loading ? '取得中…' : '表示範囲で highway を取得（最大100）'}
          </button>
        </div>
      </div>
      <p className="text-xs text-stone-500">
        範囲が広いと Overpass が重くなります。ズームしてから取得してください。バックエンドの{' '}
        <code className="rounded bg-stone-200 px-1">VITE_API_BASE</code> を frontend に設定してください。
      </p>
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="flex min-h-[200px] flex-col overflow-hidden rounded-xl border border-stone-200 bg-white">
          <div className="border-b border-stone-100 px-2 py-1 text-xs text-stone-500">
            レスポンス先頭（テキスト）
          </div>
          <pre className="min-h-0 flex-1 overflow-auto p-2 text-[11px] leading-snug text-stone-800">
            {textDump || '（未取得）'}
          </pre>
        </div>
        <div className="min-h-[280px] overflow-hidden rounded-xl border border-stone-200">
          <MapPanel
            className="h-full min-h-[280px] w-full"
            overlayGeoJson={geojson}
            onMapReady={onMapReady}
          />
        </div>
      </div>
    </div>
  )
}
