import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ConfirmDialog, type StopOptimizeConfirmVariant } from '../components/ConfirmDialog'
import { FetchRadiusErrorDialog } from '../components/FetchRadiusErrorDialog'
import { MapPanel } from '../components/MapPanel'
import { OptimizeStatusOverlay } from '../components/OptimizeStatusOverlay'
import { RouteInfoPanel } from '../components/RouteInfoPanel'
import { Sidebar, type OptimizeState } from '../components/Sidebar'
import { SketchModal } from '../components/SketchModal'
import { apiUrl } from '../lib/api'
import type { OptimizeApiResponse } from '../lib/optimizeTypes'
import {
  DEFAULT_FETCH_RADIUS_M,
  DEFAULT_SPEED_PRESET,
  FETCH_AREA_TOO_LARGE_CODE,
  type SpeedPreset,
} from '../lib/productionDefaults'
import { fitMapToFeatureCollections } from '../lib/fitMapViewport'
import { overlayForCandidate } from '../lib/routeOverlay'
import { strokesToProcessedComponents } from '../lib/singlePathPostprocess'
import type { StrokeData } from '../lib/strokeTypes'

const DEFAULT_CENTER = { lon: 139.7671, lat: 35.6812 }

function parseOptimizeApiDetail(detail: unknown): {
  fetchAreaTooLarge: boolean
  message: string
} {
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const d = detail as { code?: string; message?: string }
    if (d.code === FETCH_AREA_TOO_LARGE_CODE) {
      return {
        fetchAreaTooLarge: true,
        message: d.message ?? '探索範囲を小さくして再試行してください。',
      }
    }
    if (typeof d.message === 'string') {
      return { fetchAreaTooLarge: false, message: d.message }
    }
  }
  if (typeof detail === 'string') {
    return { fetchAreaTooLarge: false, message: detail }
  }
  return { fetchAreaTooLarge: false, message: '不明なエラーが発生しました。' }
}

export function HomePage() {
  const [targetKm, setTargetKm] = useState(10)
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokeData, setStrokeData] = useState<StrokeData | null>(null)
  const [optimizeState, setOptimizeState] = useState<OptimizeState>({ kind: 'idle' })
  const [traceRouteOverride, setTraceRouteOverride] = useState<GeoJSON.FeatureCollection | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [speedPreset, setSpeedPreset] = useState<SpeedPreset>(DEFAULT_SPEED_PRESET)
  const [fetchRadiusM, setFetchRadiusM] = useState(DEFAULT_FETCH_RADIUS_M)
  const [fetchRadiusErrorOpen, setFetchRadiusErrorOpen] = useState(false)
  const [fetchRadiusErrorMessage, setFetchRadiusErrorMessage] = useState('')
  const [mapCenter, setMapCenter] = useState(DEFAULT_CENTER)
  const [showFetchRange, setShowFetchRange] = useState(true)
  const [stopConfirmVariant, setStopConfirmVariant] = useState<StopOptimizeConfirmVariant | null>(
    null,
  )

  const optimizeGenRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)

  const onMapReady = useCallback((map: MapLibreMap) => {
    mapRef.current = map
  }, [])

  const processedComponents = useMemo(
    () => (strokeData ? strokesToProcessedComponents(strokeData.strokes) : null),
    [strokeData],
  )

  const revealFetchRange = useCallback(() => setShowFetchRange(true), [])

  // 結果が届いたら最良候補を自動選択してトレースをリセット
  useEffect(() => {
    if (optimizeState.kind === 'done') {
      const top = optimizeState.result.ranked_candidates?.[0]
      setSelectedCandidateId(top?.candidate_id ?? null)
      setTraceRouteOverride(null)
      setShowFetchRange(false)
    }
  }, [optimizeState])

  const fetchRangeCircle = useMemo(() => {
    if (!showFetchRange) return null
    if (optimizeState.kind === 'running') {
      return {
        lon: optimizeState.centerLon,
        lat: optimizeState.centerLat,
        radiusM: optimizeState.fetchRadiusM,
      }
    }
    return { lon: mapCenter.lon, lat: mapCenter.lat, radiusM: fetchRadiusM }
  }, [showFetchRange, optimizeState, mapCenter, fetchRadiusM])

  const handleSpeedPresetChange = useCallback(
    (p: SpeedPreset) => {
      setSpeedPreset(p)
      revealFetchRange()
    },
    [revealFetchRange],
  )

  const handleFetchRadiusChange = useCallback(
    (radiusM: number) => {
      setFetchRadiusM(radiusM)
      revealFetchRange()
    },
    [revealFetchRange],
  )

  const stopOptimization = useCallback(() => {
    abortRef.current?.abort()
    optimizeGenRef.current += 1
    setOptimizeState({ kind: 'idle' })
  }, [])

  const runOptimize = useCallback(
    async (preset: SpeedPreset, ignoreSourceRotation: boolean) => {
      if (!processedComponents || processedComponents.length === 0) return

      abortRef.current?.abort()
      const gen = ++optimizeGenRef.current
      const ac = new AbortController()
      abortRef.current = ac

      setOptimizeState({
        kind: 'running',
        startedAt: Date.now(),
        preset,
        centerLon: mapCenter.lon,
        centerLat: mapCenter.lat,
        fetchRadiusM,
      })
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
          fetch_radius_m: fetchRadiusM,
          ignore_source_rotation: ignoreSourceRotation,
        }

        const res = await fetch(apiUrl('/api/optimize'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: ac.signal,
        })

        if (gen !== optimizeGenRef.current) return

        if (res.status === 499) return

        if (!res.ok) {
          const payload = await res.json().catch(() => ({}))
          const parsed = parseOptimizeApiDetail(payload?.detail)
          if (parsed.fetchAreaTooLarge) {
            setFetchRadiusErrorMessage(parsed.message)
            setFetchRadiusErrorOpen(true)
            setOptimizeState({ kind: 'idle' })
            return
          }
          throw new Error(parsed.message || `サーバーエラーが発生しました（${res.status}）`)
        }

        const result: OptimizeApiResponse = await res.json()
        if (gen !== optimizeGenRef.current) return
        setOptimizeState({ kind: 'done', result })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (gen !== optimizeGenRef.current) return
        setOptimizeState({
          kind: 'error',
          message: err instanceof Error ? err.message : '不明なエラーが発生しました。',
        })
      }
    },
    [processedComponents, mapCenter, fetchRadiusM],
  )

  const handleOptimize = useCallback(
    (preset: SpeedPreset, ignoreSourceRotation: boolean) => {
      if (!processedComponents || processedComponents.length === 0) return
      if (optimizeState.kind === 'running') return
      void runOptimize(preset, ignoreSourceRotation)
    },
    [processedComponents, optimizeState.kind, runOptimize],
  )

  const handleOpenSketch = useCallback(() => {
    if (optimizeState.kind === 'running') {
      setStopConfirmVariant('sketch')
      return
    }
    setSketchOpen(true)
  }, [optimizeState.kind])

  const handleRequestStopFromOverlay = useCallback(() => {
    setStopConfirmVariant('overlay')
  }, [])

  const handleConfirmStop = useCallback(() => {
    const variant = stopConfirmVariant
    setStopConfirmVariant(null)
    if (variant == null) return

    stopOptimization()
    if (variant === 'sketch') {
      setSketchOpen(true)
    }
  }, [stopConfirmVariant, stopOptimization])

  const handleCancelStopConfirm = useCallback(() => {
    setStopConfirmVariant(null)
  }, [])

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

  useEffect(() => {
    if (optimizeState.kind !== 'done' || !selectedCandidateId) return
    const map = mapRef.current
    if (!map?.loaded()) return
    const geo = routeGeoJson
    if (!geo?.features?.length) return
    fitMapToFeatureCollections(map, geo)
  }, [optimizeState, selectedCandidateId, routeGeoJson])

  return (
    <div className="scrollbar-hidden flex h-full min-h-0 flex-col gap-0 overflow-y-auto bg-[#faf8f4] max-lg:overscroll-y-contain lg:flex-row lg:gap-5 lg:overflow-hidden">
      <Sidebar
        targetKm={targetKm}
        onTargetKmChange={setTargetKm}
        strokeData={strokeData}
        processedComponents={processedComponents}
        onOpenSketch={handleOpenSketch}
        optimizeState={optimizeState}
        speedPreset={speedPreset}
        onSpeedPresetChange={handleSpeedPresetChange}
        fetchRadiusM={fetchRadiusM}
        onFetchRadiusChange={handleFetchRadiusChange}
        onExplorationSettingsChange={revealFetchRange}
        onOptimize={handleOptimize}
      />

      <main className="flex min-w-0 shrink-0 flex-col px-3 pb-3 pt-1.5 max-lg:flex-none lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="relative flex w-full shrink-0 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] max-lg:h-[70dvh] max-lg:min-h-[320px] lg:min-h-0 lg:flex-1">
          <MapPanel
            className="min-h-0 w-full flex-1"
            onMapReady={onMapReady}
            onCenterChange={(lon, lat) => setMapCenter({ lon, lat })}
            routeGeoJson={routeGeoJson}
            fetchRangeCircle={fetchRangeCircle}
            showFetchRange={showFetchRange}
            onShowFetchRangeChange={setShowFetchRange}
          />

          <OptimizeStatusOverlay
            visible={optimizeState.kind === 'running'}
            startedAt={optimizeState.kind === 'running' ? optimizeState.startedAt : null}
            preset={optimizeState.kind === 'running' ? optimizeState.preset : 'normal'}
            onStop={handleRequestStopFromOverlay}
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

      <ConfirmDialog
        open={stopConfirmVariant != null}
        variant={stopConfirmVariant}
        onCancel={handleCancelStopConfirm}
        onConfirm={handleConfirmStop}
      />

      <FetchRadiusErrorDialog
        open={fetchRadiusErrorOpen}
        message={fetchRadiusErrorMessage}
        onClose={() => setFetchRadiusErrorOpen(false)}
      />

      {sketchOpen ? (
        <SketchModal
          onClose={() => setSketchOpen(false)}
          onConfirm={(data) => {
            setStrokeData(data)
            setSketchOpen(false)
            revealFetchRange()
            if (optimizeState.kind !== 'running') {
              setOptimizeState({ kind: 'idle' })
              setTraceRouteOverride(null)
              setSelectedCandidateId(null)
            }
          }}
        />
      ) : null}
    </div>
  )
}
