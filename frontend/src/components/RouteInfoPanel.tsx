import { useEffect, useMemo, useState } from 'react'
import { AnnealingTraceSlider } from './AnnealingTraceSlider'
import { LabelWithInfoHint } from './InfoHint'
import {
  optimizationScoreDisplayColorClass,
  optimizationScoreToDisplayPoints,
} from '../lib/optimizationScoreDisplay'
import type { OptimizeApiResponse } from '../lib/optimizeTypes'
import { rebuildRouteForTraceStep } from '../lib/routeOverlay'

const POOR_RESULT_HINT =
  '良い形が見つからなかった場合は、位置を変える・探索時間を伸ばす・より簡単な形で試すなどしてください'

export type RouteInfoPanelProps = {
  result: OptimizeApiResponse
  selectedCandidateId: string
  onCandidateChange: (id: string) => void
  onTraceOverride: (fc: GeoJSON.FeatureCollection | null) => void
}

export function RouteInfoPanel({
  result,
  selectedCandidateId,
  onCandidateChange,
  onTraceOverride,
}: RouteInfoPanelProps) {
  const [traceOpen, setTraceOpen] = useState(false)
  const [traceStepIdx, setTraceStepIdx] = useState(0)

  const ranked = result.ranked_candidates ?? []
  const currentIdx = ranked.findIndex((c) => c.candidate_id === selectedCandidateId)
  const selectedCandidate = ranked[currentIdx] ?? ranked[0]

  // Trace from the candidate's own restart (not always restart 0)
  const candidateRestart = result.restarts.find(
    (r) => r.restart_index === selectedCandidate?.restart_index,
  )
  const traceSteps = candidateRestart?.trace_steps ?? []
  const edgesFc = result.edges_geojson
  const hasTrace = traceSteps.length > 0 && edgesFc != null

  // Array index in traceSteps where this candidate was recorded
  const candidateArrayIdx = useMemo(() => {
    if (!selectedCandidate || !traceSteps.length) return 0
    const idx = traceSteps.findIndex((s) => s.step_index === selectedCandidate.step_index)
    return idx >= 0 ? idx : Math.max(0, traceSteps.length - 1)
    // selectedCandidateId change → selectedCandidate + traceSteps both update
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCandidateId])

  // Amber when slider is at the candidate's position, blue elsewhere
  const isAtCandidatePos = traceStepIdx === candidateArrayIdx

  // When candidate changes: reset slider to the new candidate's position
  useEffect(() => {
    setTraceStepIdx(candidateArrayIdx)
    if (traceOpen && edgesFc) {
      const step = traceSteps[candidateArrayIdx]
      if (step) onTraceOverride(rebuildRouteForTraceStep(step, edgesFc))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCandidateId])

  function handleCandidateChange(id: string) {
    // traceOpen is preserved; useEffect above handles slider + overlay update
    onCandidateChange(id)
  }

  function handlePrev() {
    if (currentIdx > 0) handleCandidateChange(ranked[currentIdx - 1].candidate_id)
  }

  function handleNext() {
    if (currentIdx < ranked.length - 1) handleCandidateChange(ranked[currentIdx + 1].candidate_id)
  }

  function handleTraceToggle() {
    if (traceOpen) {
      setTraceOpen(false)
      onTraceOverride(null)
    } else {
      setTraceOpen(true)
      setTraceStepIdx(candidateArrayIdx)
      if (edgesFc) {
        const step = traceSteps[candidateArrayIdx]
        if (step) onTraceOverride(rebuildRouteForTraceStep(step, edgesFc))
      }
    }
  }

  function handleTraceStepChange(idx: number) {
    setTraceStepIdx(idx)
    const step = traceSteps[idx]
    if (!step || !edgesFc) {
      onTraceOverride(null)
      return
    }
    onTraceOverride(rebuildRouteForTraceStep(step, edgesFc))
  }

  // Move slider back to the candidate's position (don't close the section)
  function handleGoToCandidatePos() {
    setTraceStepIdx(candidateArrayIdx)
    if (edgesFc) {
      const step = traceSteps[candidateArrayIdx]
      if (step) onTraceOverride(rebuildRouteForTraceStep(step, edgesFc))
    }
  }

  const distanceKm = selectedCandidate?.route_length_km ?? result.route_length_km
  const matchPoints =
    selectedCandidate != null
      ? optimizationScoreToDisplayPoints(selectedCandidate.score_total)
      : null
  const matchColorClass =
    matchPoints != null ? optimizationScoreDisplayColorClass(matchPoints) : ''
  const formatDisplayScore = (raw: number) =>
    `${optimizationScoreToDisplayPoints(raw)}点`

  return (
    <div className="pointer-events-auto absolute bottom-4 left-1/2 z-10 w-64 max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-xl border border-stone-200/80 bg-white/95 px-3.5 py-3 shadow-lg backdrop-blur-sm sm:left-4 sm:max-w-none sm:translate-x-0">
      <div className="mb-2">
        <LabelWithInfoHint
          label="探索結果"
          hintLabel="探索結果について"
          className="text-sm text-stone-700"
        >
          {POOR_RESULT_HINT}
        </LabelWithInfoHint>
      </div>

      {/* マッチ度 */}
      {matchPoints != null && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-stone-500">マッチ度</span>
          <span className={`text-sm font-semibold tabular-nums ${matchColorClass}`}>
            {matchPoints}点
          </span>
        </div>
      )}

      {/* ルート距離 */}
      <div className={`flex items-center justify-between ${matchPoints != null ? 'mt-1.5' : ''}`}>
        <span className="text-xs text-stone-500">ルート距離</span>
        <span className="text-sm font-semibold text-stone-900">
          {distanceKm != null ? `${distanceKm.toFixed(2)} km` : '—'}
        </span>
      </div>

      {/* 候補切り替え（複数候補時のみ） */}
      {ranked.length >= 2 && (
        <div className="mt-2 flex items-center gap-1">
          <button
            type="button"
            onClick={handlePrev}
            disabled={currentIdx <= 0}
            className="flex h-6 w-6 items-center justify-center rounded-md text-stone-400 hover:enabled:bg-stone-100 hover:enabled:text-stone-700 disabled:opacity-30"
            aria-label="前の候補"
          >
            ‹
          </button>
          <div className="flex flex-1 items-center justify-center gap-1.5 text-xs text-stone-600">
            <span>候補 {currentIdx + 1} / {ranked.length}</span>
            {selectedCandidate?.tier === 'best' && (
              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                ベスト
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleNext}
            disabled={currentIdx >= ranked.length - 1}
            className="flex h-6 w-6 items-center justify-center rounded-md text-stone-400 hover:enabled:bg-stone-100 hover:enabled:text-stone-700 disabled:opacity-30"
            aria-label="次の候補"
          >
            ›
          </button>
        </div>
      )}

      {/* 探索トレース */}
      {hasTrace && (
        <div className="mt-2 border-t border-stone-100 pt-2">
          <button
            type="button"
            onClick={handleTraceToggle}
            className="flex w-full items-center justify-between text-xs text-[#4a6f8a] hover:underline"
          >
            <span>探索の様子を見る</span>
            <span className="text-[10px]">{traceOpen ? '▲' : '▼'}</span>
          </button>

          {traceOpen && (
            <div className="mt-1">
              <AnnealingTraceSlider
                steps={traceSteps}
                showBestRoute={isAtCandidatePos}
                onShowBestRoute={handleGoToCandidatePos}
                selectedTraceIndex={traceStepIdx}
                traceSliderValue={traceStepIdx}
                onTraceSliderChange={handleTraceStepChange}
                showBestLabel="候補地点を表示中"
                returnToBestLabel="候補地点に戻す"
                formatScore={formatDisplayScore}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
