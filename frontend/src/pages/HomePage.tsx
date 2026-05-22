import { useEffect, useMemo, useState } from 'react'
import { MapPanel } from '../components/MapPanel'
import { OptimizeStatusOverlay } from '../components/OptimizeStatusOverlay'
import { RouteInfoPanel } from '../components/RouteInfoPanel'
import { Sidebar, type OptimizeState } from '../components/Sidebar'
import { SketchModal } from '../components/SketchModal'
import { apiUrl } from '../lib/api'
import type { OptimizeApiResponse } from '../lib/optimizeTypes'
import {
  DEFAULT_SPEED_PRESET,
  PRESET_FETCH_RADIUS_M,
  type SpeedPreset,
} from '../lib/productionDefaults'
import { overlayForCandidate } from '../lib/routeOverlay'
import { strokesToProcessedComponents } from '../lib/singlePathPostprocess'
import type { StrokeData } from '../lib/strokeTypes'

const DEFAULT_CENTER = { lon: 139.7671, lat: 35.6812 }

export function HomePage() {
  const [targetKm, setTargetKm] = useState(10)
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokeData, setStrokeData] = useState<StrokeData | null>(null)
  const [optimizeState, setOptimizeState] = useState<OptimizeState>({ kind: 'idle' })
  const [traceRouteOverride, setTraceRouteOverride] = useState<GeoJSON.FeatureCollection | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [speedPreset, setSpeedPreset] = useState<SpeedPreset>(DEFAULT_SPEED_PRESET)
  const [mapCenter, setMapCenter] = useState(DEFAULT_CENTER)

  const processedComponents = useMemo(
    () => (strokeData ? strokesToProcessedComponents(strokeData.strokes) : null),
    [strokeData],
  )

  // 結果が届いたら最良候補を自動選択してトレースをリセット
  useEffect(() => {
    if (optimizeState.kind === 'done') {
      const top = optimizeState.result.ranked_candidates?.[0]
      setSelectedCandidateId(top?.candidate_id ?? null)
      setTraceRouteOverride(null)
    }
  }, [optimizeState])

  // 取得範囲 circle: 探索中以外は常に表示
  const fetchRangeCircle = useMemo(
    () =>
      optimizeState.kind !== 'running'
        ? { lon: mapCenter.lon, lat: mapCenter.lat, radiusM: PRESET_FETCH_RADIUS_M[speedPreset] }
        : null,
    [optimizeState.kind, mapCenter, speedPreset],
  )

  async function handleOptimize(preset: SpeedPreset, ignoreSourceRotation: boolean) {
    if (!processedComponents || processedComponents.length === 0) return

    setOptimizeState({ kind: 'running', startedAt: Date.now(), preset })
    setTraceRouteOverride(null)
    setSelectedCandidateId(null)

    try {
      const body = {
        stroke_components: processedComponents.map((comp) =>
          comp.map((p) => ({ x: p.x, y: p.y })),
        ),
        center_lon: mapCenter.lon,
        center_lat: mapCenter.lat,
        speed_preset: preset,
        ignore_source_rotation: ignoreSourceRotation,
      }

      const res = await fetch(apiUrl('/api/optimize'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail?.detail ?? `サーバーエラーが発生しました（${res.status}）`)
      }

      const result: OptimizeApiResponse = await res.json()
      setOptimizeState({ kind: 'done', result })
    } catch (err) {
      setOptimizeState({
        kind: 'error',
        message: err instanceof Error ? err.message : '不明なエラーが発生しました。',
      })
    }
  }

  // 選択候補のルートを表示（トレースオーバーライドが優先）
  const routeGeoJson = useMemo(() => {
    if (traceRouteOverride) return traceRouteOverride
    if (optimizeState.kind !== 'done') return null
    const { candidates_geojson, ranked_candidates } = optimizeState.result
    if (!selectedCandidateId || !ranked_candidates?.length) return candidates_geojson
    const fc = overlayForCandidate(
      selectedCandidateId,
      candidates_geojson,
      ranked_candidates,
      optimizeState.result.edges_geojson,
    )
    return fc ?? candidates_geojson
  }, [traceRouteOverride, optimizeState, selectedCandidateId])

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <Sidebar
        targetKm={targetKm}
        onTargetKmChange={setTargetKm}
        strokeData={strokeData}
        processedComponents={processedComponents}
        onOpenSketch={() => setSketchOpen(true)}
        optimizeState={optimizeState}
        speedPreset={speedPreset}
        onSpeedPresetChange={setSpeedPreset}
        onOptimize={handleOptimize}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col px-3 pb-3 pt-1.5 lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="relative flex min-h-[280px] flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] lg:min-h-0">
          <MapPanel
            className="min-h-0 w-full flex-1"
            onCenterChange={(lon, lat) => setMapCenter({ lon, lat })}
            routeGeoJson={routeGeoJson}
            fetchRangeCircle={fetchRangeCircle}
          />

          <OptimizeStatusOverlay
            visible={optimizeState.kind === 'running'}
            startedAt={optimizeState.kind === 'running' ? optimizeState.startedAt : null}
            preset={optimizeState.kind === 'running' ? optimizeState.preset : 'normal'}
          />

          {optimizeState.kind === 'done' && selectedCandidateId && (
            <RouteInfoPanel
              result={optimizeState.result}
              selectedCandidateId={selectedCandidateId}
              onCandidateChange={setSelectedCandidateId}
              onTraceOverride={setTraceRouteOverride}
            />
          )}
        </div>
      </main>

      {sketchOpen ? (
        <SketchModal
          onClose={() => setSketchOpen(false)}
          onConfirm={(data) => {
            setStrokeData(data)
            setSketchOpen(false)
            setOptimizeState({ kind: 'idle' })
            setTraceRouteOverride(null)
            setSelectedCandidateId(null)
          }}
        />
      ) : null}
    </div>
  )
}
