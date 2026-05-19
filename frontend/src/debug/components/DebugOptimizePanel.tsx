import { useEffect, useMemo, useState } from 'react'
import { MdOutlineDraw } from 'react-icons/md'
import { SketchModal } from '../../components/SketchModal'
import { SketchPreview } from '../../components/SketchPreview'
import { apiUrl } from '../../lib/api'
import type { Point } from '../../lib/simplify'
import { buildSinglePath } from '../../lib/singlePathPostprocess'
import { findConnectedComponents } from '../../lib/strokeConnectivity'
import type { StrokeData } from '../../lib/strokeTypes'
import { SinglePathDebugPreview } from './SinglePathDebugPreview'
import {
  normalizeGraphBuildOptions,
  type GraphBuildOptionsPayload,
  type GraphPreviewResponse,
} from '../lib/graphPreview'
import {
  DEFAULT_ANNEAL_SEED,
  DEFAULT_FINAL_TEMPERATURE,
  DEFAULT_IGNORE_OPTIMIZATION_BUDGET,
  DEFAULT_IGNORE_SOURCE_ROTATION,
  DEFAULT_INITIAL_TEMPERATURE,
  DEFAULT_LOG_SCALE_STEP,
  DEFAULT_MAX_ITERATIONS,
  DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
  DEFAULT_RESTART_COUNT,
  DEFAULT_ROTATION_STEP_RAD,
  DEFAULT_TRACE_STRIDE,
  DEFAULT_TRANSLATION_STEP_M_RATIO,
  DEFAULT_WEIGHT_DIJKSTRA_FALLBACK,
  DEFAULT_WEIGHT_OUT_OF_GRAPH,
  DEFAULT_WEIGHT_SHAPE_DISTANCE,
  DEFAULT_WEIGHT_SOURCE_ROTATION,
  DEFAULT_WEIGHT_SOURCE_SCALE,
  DEFAULT_WEIGHT_TURN,
  DEFAULT_WEIGHT_UNREACHABLE,
} from '../lib/optimizationDefaults'
import { rebuildRouteFeatureCollection } from '../lib/rebuildRouteFromTraceStep'
import { DebugAnnealingTraceSlider } from './DebugAnnealingTraceSlider'

export type OptimizeTraceStep = {
  step_index: number
  temperature: number
  accepted: boolean
  score_total: number
  score_terms: Record<string, number>
  transform: Record<string, number>
  edge_ids: string[]
  edge_ids_per_component?: string[][]
}

export type OptimizeRestartResult = {
  restart_index: number
  seed: number
  initial_transform: Record<string, number>
  best_transform: Record<string, number>
  best_edge_ids: string[]
  best_score: number
  best_breakdown: Record<string, number>
  route_length_m?: number
  route_length_km?: number
  iterations_planned: number
  iterations_completed: number
  accepted_moves: number
  acceptance_rate: number
  deadline_hit: boolean
  trace_steps: OptimizeTraceStep[]
}

export type OptimizeComponentResult = {
  component_index: number
  best_score: number
  best_breakdown: Record<string, number>
  route_length_m: number
  route_length_km: number
}

export type OptimizeApiResponse = {
  trace_format_version: number
  projection: GraphPreviewResponse['projection']
  projection_summary?: string
  stats: Record<string, number>
  candidates_geojson: GeoJSON.FeatureCollection
  best_score: number
  best_breakdown: Record<string, number>
  best_restart_index: number
  /** ベストルートのグラフ上の長さ（メートル） */
  route_length_m?: number
  /** 同上（キロメートル）。評価とは独立した表示用メタ情報 */
  route_length_km?: number
  optimizer_meta?: Record<string, unknown>
  restarts: OptimizeRestartResult[]
  /** コンポーネントごとの結果（single_path では1要素） */
  components?: OptimizeComponentResult[]
}

export type DebugOptimizePanelProps = {
  geojson: GeoJSON.FeatureCollection | null
  graphOptions: GraphBuildOptionsPayload
  graphPreview: GraphPreviewResponse | null
  onBack: () => void
  getMapBounds: () => {
    min_lon: number
    min_lat: number
    max_lon: number
    max_lat: number
  } | null
  /** 地図に重ねるルート（トレーススライダーまたはベスト） */
  onRouteOverlayChange: (fc: GeoJSON.FeatureCollection | null) => void
}

/** トレース内で score_total が最小のステップ番号（その試行内ベスト） */
function bestTraceStepIndex(trace: OptimizeTraceStep[]): number {
  if (trace.length === 0) return 0
  let bestIdx = 0
  let bestScore = Infinity
  for (let i = 0; i < trace.length; i++) {
    if (trace[i].score_total < bestScore) {
      bestScore = trace[i].score_total
      bestIdx = i
    }
  }
  return bestIdx
}

export function DebugOptimizePanel({
  geojson,
  graphOptions,
  graphPreview,
  onBack,
  getMapBounds,
  onRouteOverlayChange,
}: DebugOptimizePanelProps) {
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokeData, setStrokeData] = useState<StrokeData | null>(null)
  const [processedComponents, setProcessedComponents] = useState<Point[][] | null>(null)
  const [showDebugPreview, setShowDebugPreview] = useState(true)
  const [seed, setSeed] = useState(DEFAULT_ANNEAL_SEED)
  const [budgetSeconds, setBudgetSeconds] = useState(DEFAULT_OPTIMIZATION_BUDGET_SECONDS)
  const [maxIterations, setMaxIterations] = useState(DEFAULT_MAX_ITERATIONS)
  const [restartCount, setRestartCount] = useState(DEFAULT_RESTART_COUNT)
  const [ignoreSourceRotation, setIgnoreSourceRotation] = useState(DEFAULT_IGNORE_SOURCE_ROTATION)
  const [ignoreTimeLimit, setIgnoreTimeLimit] = useState(DEFAULT_IGNORE_OPTIMIZATION_BUDGET)
  const [initialTemperature, setInitialTemperature] = useState(DEFAULT_INITIAL_TEMPERATURE)
  const [finalTemperature, setFinalTemperature] = useState(DEFAULT_FINAL_TEMPERATURE)
  const [translationStepRatio, setTranslationStepRatio] = useState(DEFAULT_TRANSLATION_STEP_M_RATIO)
  const [rotationStepRad, setRotationStepRad] = useState(DEFAULT_ROTATION_STEP_RAD)
  const [logScaleStep, setLogScaleStep] = useState(DEFAULT_LOG_SCALE_STEP)
  const [traceStride, setTraceStride] = useState(DEFAULT_TRACE_STRIDE)
  const [weightSourceRotation, setWeightSourceRotation] = useState(DEFAULT_WEIGHT_SOURCE_ROTATION)
  const [weightSourceScale, setWeightSourceScale] = useState(DEFAULT_WEIGHT_SOURCE_SCALE)
  const [weightShapeDistance, setWeightShapeDistance] = useState(DEFAULT_WEIGHT_SHAPE_DISTANCE)
  const [weightTurn, setWeightTurn] = useState(DEFAULT_WEIGHT_TURN)
  const [weightUnreachable, setWeightUnreachable] = useState(DEFAULT_WEIGHT_UNREACHABLE)
  const [weightOutOfGraph, setWeightOutOfGraph] = useState(DEFAULT_WEIGHT_OUT_OF_GRAPH)
  const [weightDijkstraFallback, setWeightDijkstraFallback] = useState(DEFAULT_WEIGHT_DIJKSTRA_FALLBACK)
  const [loading, setLoading] = useState(false)
  const [loadingStartedAt, setLoadingStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<OptimizeApiResponse | null>(null)
  /** true のとき全体ベストの GeoJSON（最良試行を選んでいるときのみ UI 上も「ベスト候補」） */
  const [showBestRoute, setShowBestRoute] = useState(true)
  const [selectedRestartIndex, setSelectedRestartIndex] = useState(0)
  const [selectedTraceIndex, setSelectedTraceIndex] = useState(0)

  const optsNorm = useMemo(() => normalizeGraphBuildOptions(graphOptions), [graphOptions])

  const hasShape = Boolean(strokeData && strokeData.strokes.some((s) => s.length >= 2))
  const restarts = result?.restarts ?? []
  const selectedRestart = restarts.find((r) => r.restart_index === selectedRestartIndex) ?? restarts[0] ?? null
  const steps = selectedRestart?.trace_steps ?? []
  const maxStepIdx = Math.max(0, steps.length - 1)

  useEffect(() => {
    if (!loading || loadingStartedAt == null) return
    const update = () => setElapsedSeconds((Date.now() - loadingStartedAt) / 1000)
    update()
    const id = window.setInterval(update, 250)
    return () => window.clearInterval(id)
  }, [loading, loadingStartedAt])

  useEffect(() => {
    if (!result) {
      onRouteOverlayChange(null)
      return
    }
    if (showBestRoute) {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    const edges = graphPreview?.graph_geojson?.edges
    if (!edges) {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    const step = steps[selectedTraceIndex]
    if (!step) {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    if (step.edge_ids_per_component && step.edge_ids_per_component.length > 1) {
      // 全コンポーネントのトレース地点ルートを再構築して合成
      const features = step.edge_ids_per_component.flatMap(
        (ids) => rebuildRouteFeatureCollection(ids, edges).features,
      )
      onRouteOverlayChange({ type: 'FeatureCollection', features })
    } else {
      onRouteOverlayChange(rebuildRouteFeatureCollection(step.edge_ids, edges))
    }
  }, [result, showBestRoute, steps, selectedTraceIndex, graphPreview, onRouteOverlayChange])

  useEffect(() => {
    if (!result) return
    const bestIndex = result.best_restart_index
    setSelectedRestartIndex((current) =>
      result.restarts.some((r) => r.restart_index === current) ? current : bestIndex,
    )
  }, [result])

  /** グローバルベスト表示は最良試行を選んでいるときだけ有効 */
  useEffect(() => {
    if (!result) return
    if (!showBestRoute) return
    if (selectedRestartIndex !== result.best_restart_index) {
      setShowBestRoute(false)
    }
  }, [result, showBestRoute, selectedRestartIndex])

  useEffect(() => {
    setSelectedTraceIndex((current) => Math.min(current, maxStepIdx))
  }, [selectedRestartIndex, maxStepIdx])

  const runOptimize = async () => {
    if (!geojson?.features?.length || !strokeData) {
      setError('道路データ・手書きの形の両方が必要です。')
      return
    }
    const strokeComponents = processedComponents ?? [strokeData.strokes[0] ?? []]
    if (strokeComponents.every((c) => c.length < 2)) {
      setError('有効なストロークがありません。')
      return
    }
    const bbox = getMapBounds()
    if (!bbox) {
      setError('地図の範囲を取得できませんでした。')
      return
    }
    setLoading(true)
    setLoadingStartedAt(Date.now())
    setElapsedSeconds(0)
    setError(null)
    try {
      const body = {
        geojson,
        bbox,
        options: optsNorm,
        stroke_components: strokeComponents.map((comp) => comp.map((p) => ({ x: p.x, y: p.y }))),
        stroke_mode: strokeData.strokeMode,
        record_trace: true,
        weights: {
          source_rotation: weightSourceRotation,
          source_scale: weightSourceScale,
          shape_distance: weightShapeDistance,
          turn: weightTurn,
          unreachable: weightUnreachable,
          out_of_graph: weightOutOfGraph,
          dijkstra_fallback: weightDijkstraFallback,
        },
        anneal: {
          optimization_budget_seconds: budgetSeconds,
          seed,
          max_iterations: maxIterations,
          restart_count: restartCount,
          ignore_optimization_budget: ignoreTimeLimit,
          ignore_source_rotation: ignoreSourceRotation,
          initial_temperature: initialTemperature,
          final_temperature: finalTemperature,
          translation_step_m_ratio: translationStepRatio,
          rotation_step_rad: rotationStepRad,
          log_scale_step: logScaleStep,
          trace_stride: traceStride,
        },
      }
      const res = await fetch(apiUrl('/api/debug/optimize'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || res.statusText)
      }
      const data = (await res.json()) as OptimizeApiResponse
      setResult(data)
      const br = data.best_restart_index
      setSelectedRestartIndex(br)
      const bestRun = data.restarts.find((r) => r.restart_index === br)
      setSelectedTraceIndex(bestTraceStepIndex(bestRun?.trace_steps ?? []))
      setShowBestRoute(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setLoadingStartedAt(null)
    }
  }

  const bestTraceIndex = useMemo(() => bestTraceStepIndex(steps), [steps])

  const traceSliderValue = showBestRoute ? bestTraceIndex : selectedTraceIndex

  return (
    <aside className="flex min-h-0 w-full flex-1 flex-col gap-4.5 overflow-hidden p-5 pb-4 lg:max-w-sm lg:h-full lg:flex-none lg:min-h-0 lg:overflow-visible lg:shrink-0 lg:py-5 lg:pl-5 lg:pr-0">
      <div className="shrink-0 flex flex-col gap-2.5">
        <button
          type="button"
          onClick={onBack}
          className="w-fit shrink-0 text-left text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline"
        >
          ← 前処理に戻る
        </button>
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">形の探索</h1>
        <p className="text-xs leading-relaxed text-stone-600">
          現在のグラフと表示範囲をそのまま使い、手書きの形に近い道路ルートを<strong>焼きなまし</strong>
          （回転・スケール・並進の遷移）で選びます。辺数が多い bbox は前処理で範囲を絞ると応答が安定します。
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain rounded-xl border border-stone-200/90 bg-white/80 p-3 shadow-sm">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3">
            <button
              type="button"
              className="inline-flex items-center justify-center gap-1 rounded-xl border border-dashed border-stone-400 bg-white py-3 text-sm font-medium text-stone-800 shadow-sm hover:border-[#4a6f8a] hover:bg-[#f3f6f8]"
              onClick={() => setSketchOpen(true)}
            >
              <MdOutlineDraw className="h-5 w-5 shrink-0 text-stone-700" aria-hidden />
              {hasShape ? '形を描き直す' : '形を描く'}
            </button>
            {hasShape && strokeData ? (
              <>
                {strokeData.strokeMode === 'free_draw' &&
                  (processedComponents?.length ?? 0) > 1 && (
                    <p className="text-[11px] text-stone-500">
                      自由描画モード: {processedComponents?.length} コンポーネントをジョイント最適化
                    </p>
                  )}
                {processedComponents ? (
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] text-stone-500">後処理済みパス</p>
                      <button
                        type="button"
                        className="rounded px-1.5 py-0.5 text-[10px] font-medium text-stone-400 hover:bg-stone-100 hover:text-stone-600"
                        onClick={() => setShowDebugPreview((v) => !v)}
                      >
                        {showDebugPreview ? '通常表示' : '巡回順'}
                      </button>
                    </div>
                    {showDebugPreview ? (
                      <SinglePathDebugPreview
                        paths={processedComponents}
                        className="aspect-square mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
                      />
                    ) : (
                      <SketchPreview
                        strokes={processedComponents}
                        className="aspect-square mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
                      />
                    )}
                  </div>
                ) : (
                  <SketchPreview
                    strokes={strokeData.strokes}
                    className="aspect-square mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
                  />
                )}
              </>
            ) : null}
          </div>

          <details open className="rounded-lg border border-stone-200/80 bg-stone-50/50 p-2">
            <summary className="cursor-pointer text-xs py-0.5 font-medium text-stone-700">焼きなましの設定</summary>
            <div className="mt-2.5 flex flex-col gap-2">
              <label className="text-xs text-stone-600">
                初期解の数（試行数）
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={restartCount}
                  onChange={(e) => setRestartCount(Math.min(64, Math.max(1, Number(e.target.value) || 1)))}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                <span>時間上限（秒）</span>
                <input
                  type="number"
                  min={0.5}
                  max={120}
                  step={0.5}
                  value={budgetSeconds}
                  disabled={ignoreTimeLimit}
                  onChange={(e) => setBudgetSeconds(Math.min(120, Math.max(0.05, Number(e.target.value) || 10)))}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm disabled:opacity-40"
                />
              </label>
              <label className="text-xs text-stone-600">
                トレース間隔
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={traceStride}
                  onChange={(e) => setTraceStride(Math.min(10000, Math.max(1, Number(e.target.value) || 1)))}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                />
              </label>
              <label className="mt-1 flex items-center gap-2 text-xs text-stone-700">
                <input
                  type="checkbox"
                  checked={ignoreSourceRotation}
                  onChange={(e) => setIgnoreSourceRotation(e.target.checked)}
                  className="h-4 w-4 accent-[#4a6f8a]"
                />
                角度は気にしない
              </label>
              <label className="flex items-center gap-2 text-xs text-stone-700">
                <input
                  type="checkbox"
                  checked={ignoreTimeLimit}
                  onChange={(e) => setIgnoreTimeLimit(e.target.checked)}
                  className="h-4 w-4 accent-[#4a6f8a]"
                />
                実行時間上限を無視する
              </label>
              <details className="mt-1.5 rounded-lg border border-stone-200/80 bg-white/70 p-2">
                <summary className="cursor-pointer text-xs py-0.5 text-stone-700">
                  開発者向けの詳細設定
                </summary>
                <div className="mt-2.5 flex flex-col gap-2">
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>乱数シード</span>
                    <input
                      type="number"
                      value={seed}
                      onChange={(e) => setSeed(Number(e.target.value) || 0)}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>最大反復数</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      各試行（初期解）ごとに実行するステップ数の上限。
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={20000}
                      value={maxIterations}
                      onChange={(e) => setMaxIterations(Math.min(20000, Math.max(1, Number(e.target.value) || 1)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>初期温度</span>
                    <input
                      type="number"
                      min={0.000001}
                      max={10}
                      step={0.001}
                      value={initialTemperature}
                      onChange={(e) => setInitialTemperature(Math.min(10, Math.max(0.000001, Number(e.target.value) || 0.05)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>最終温度</span>
                    <input
                      type="number"
                      min={0.000001}
                      max={10}
                      step={0.001}
                      value={finalTemperature}
                      onChange={(e) => setFinalTemperature(Math.min(10, Math.max(0.000001, Number(e.target.value) || 0.001)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <p className="mt-2 text-[10px] font-medium text-stone-500">遷移ステップ</p>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>並進ステップ（bbox 比）</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      1ステップの平行移動量の標準偏差をグラフ幅・高さの何倍にするか。大きいほど1ステップで遠くに移動します。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.01}
                      value={translationStepRatio}
                      onChange={(e) => setTranslationStepRatio(Math.min(2, Math.max(0, Number(e.target.value) || 0)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>回転ステップ（rad）</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      1ステップの回転量の標準偏差（ラジアン）。π≈3.14 で半回転相当のステップ幅になります。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={6.28319}
                      step={0.01}
                      value={rotationStepRad}
                      onChange={(e) => setRotationStepRad(Math.min(6.28319, Math.max(0, Number(e.target.value) || 0)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>スケールステップ（log）</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      1ステップのスケール変化の標準偏差（log スケール）。log(scale) に加算されます。0.12 で約 1 段階のスケール変化に相当します。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.01}
                      value={logScaleStep}
                      onChange={(e) => setLogScaleStep(Math.min(2, Math.max(0, Number(e.target.value) || 0)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <p className="mt-2 text-[10px] font-medium text-stone-500">スコア重み</p>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>shape_distance 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      ターゲット折れ線とルートの形状類似度（弧長対応距離＋coverage、bbox 対角で正規化）に乗じる重み。最も重要なスコア項です。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={10}
                      step={0.1}
                      value={weightShapeDistance}
                      onChange={(e) => setWeightShapeDistance(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>out_of_graph 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      グラフ bbox 外への逸脱ペナルティ。形がグラフ境界付近に押し込まれた状態（絡まりの原因）から脱出する勾配を生み出します。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={20}
                      step={0.1}
                      value={weightOutOfGraph}
                      onChange={(e) => setWeightOutOfGraph(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>dijkstra_fallback 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      smooth DP スナップが失敗して Dijkstra 最短路にフォールバックした区間の割合に乗じる重み。形が道路グラフに乗れていない度合いを反映します。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.05}
                      value={weightDijkstraFallback}
                      onChange={(e) => setWeightDijkstraFallback(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>source_rotation 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      入力ストロークの向きからの回転角ペナルティに乗じる重み。30° 以内は無罰で、超過分を正規化します。「角度は気にしない」ON で無効化されます。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.01}
                      value={weightSourceRotation}
                      onChange={(e) => setWeightSourceRotation(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>source_scale 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      スケール変形の大きさ（|log(scale)|）に乗じる重み。元のサイズ（scale=1）から離れるほどペナルティが増えます。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.01}
                      value={weightSourceScale}
                      onChange={(e) => setWeightSourceScale(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>turn 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      曲がり角の絶対値和を正規化した項に乗じる重み。上げると折り返しや急カーブが少ないルートを優先します。
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.01}
                      value={weightTurn}
                      onChange={(e) => setWeightTurn(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-xs text-stone-600">
                    <span>unreachable 重み</span>
                    <span className="text-[10px] font-normal leading-snug text-stone-500">
                      ルートが連結できなかった（到達不能）場合のペナルティに乗じる重み。既定 1e6 で実質必須の罰則となります。
                    </span>
                    <input
                      type="number"
                      min={0}
                      step={1000}
                      value={weightUnreachable}
                      onChange={(e) => setWeightUnreachable(Math.max(0, Number(e.target.value) || 0))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                </div>
              </details>
            </div>
          </details>

          <button
            type="button"
            disabled={loading || !hasShape}
            onClick={() => void runOptimize()}
            className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-50"
          >
            {loading ? '探索中…' : '焼きなましを実行'}
          </button>

          {loading ? (
            <p className="text-[11px] leading-snug text-stone-500" aria-live="polite">
              焼きなまし中... {elapsedSeconds.toFixed(1)}s{ignoreTimeLimit ? ' (時間上限なし)' : `, 上限 ${budgetSeconds}s`},{' '}
              最大 {maxIterations} iterations / {restartCount} 試行
            </p>
          ) : result ? (
            <p className="text-[11px] leading-snug text-stone-500">
              試行 {restarts.length} 件 / 選択中トレース {steps.length} 件
              {typeof result.optimizer_meta?.grid_search_candidates === 'number'
                ? ` / グリッド ${result.optimizer_meta.grid_search_candidates as number} 点評価`
                : ''}
              {result.optimizer_meta?.deadline_hit === true ? ' / 時間上限で停止' : ''}
            </p>
          ) : null}

          {error ? <p className="text-sm text-red-700">{error}</p> : null}

          {result ? (
            <div className="flex flex-col gap-3 border-t border-stone-200/80 pt-3">
              <div className="flex flex-col gap-1">
                <p className="text-xs text-stone-700">
                  ベストスコア: <span className="font-mono">{result.best_score.toFixed(4)}</span>
                  {' / '}ベスト試行:{' '}
                  <span className="font-mono">#{result.best_restart_index}</span>
                </p>
                {typeof result.route_length_km === 'number' ? (
                  <p className="text-xs text-stone-700">
                    ルートの長さ:{' '}
                    <span className="font-mono">{result.route_length_km.toFixed(3)} km</span>
                  </p>
                ) : null}
              </div>
              <ul className="grid grid-cols-2 gap-1 text-[11px] text-stone-600">
                {Object.entries(result.best_breakdown).map(([k, v]) => (
                  <li key={k} className="font-mono">
                    {k}: {typeof v === 'number' ? v.toFixed(4) : v}
                  </li>
                ))}
              </ul>
              {restarts.length > 0 ? (
                <div className="rounded-lg border border-stone-200/80 bg-stone-50/50 p-2">
                  <p className="mb-1 text-xs font-medium text-stone-700">各試行の結果</p>
                  <ul className="flex max-h-24 flex-col gap-1 overflow-y-auto text-[10px] text-stone-600">
                    {restarts.map((r) => (
                      <li key={r.restart_index} className="font-mono">
                        #{r.restart_index}
                        {r.restart_index === result.best_restart_index ? ' 最良' : ''}: スコア=
                        {r.best_score.toFixed(4)}, 採択率={(r.acceptance_rate * 100).toFixed(1)}%, 初期角度=
                        {((r.initial_transform.theta_rad ?? 0) * 180 / Math.PI).toFixed(1)}°, scale=
                        {(r.initial_transform.scale ?? 0).toFixed(2)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {selectedRestart ? (
                <div className="mt-0.5 flex flex-col gap-2">
                  <label className="text-xs text-stone-600">
                    試行
                    <select
                      value={selectedRestartIndex}
                      onChange={(e) => {
                        const next = Number(e.target.value)
                        const r = restarts.find((rr) => rr.restart_index === next)
                        setSelectedRestartIndex(next)
                        setSelectedTraceIndex(bestTraceStepIndex(r?.trace_steps ?? []))
                        setShowBestRoute(false)
                      }}
                      className="mt-0.5 w-full rounded border border-stone-200 bg-white px-2 py-1 text-sm"
                    >
                      {restarts.map((r) => (
                        <option key={r.restart_index} value={r.restart_index}>
                          #{r.restart_index}
                          {r.restart_index === result.best_restart_index ? ' 最良' : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                  <DebugAnnealingTraceSlider
                    steps={steps}
                    bestRestartIndex={result.best_restart_index}
                    selectedRestartIndex={selectedRestart.restart_index}
                    showBestRoute={showBestRoute}
                    onShowBestRoute={() => {
                      const br = result.best_restart_index
                      const bestRun = result.restarts.find((r) => r.restart_index === br)
                      setSelectedRestartIndex(br)
                      setSelectedTraceIndex(bestTraceStepIndex(bestRun?.trace_steps ?? []))
                      setShowBestRoute(true)
                    }}
                    selectedTraceIndex={selectedTraceIndex}
                    traceSliderValue={traceSliderValue}
                    onTraceSliderChange={(index) => {
                      setSelectedTraceIndex(index)
                      setShowBestRoute(false)
                    }}
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {graphPreview?.stats ? (
            <p className="text-[11px] text-stone-500">
              グラフ: 辺 {graphPreview.stats.edge_count ?? '—'} / 頂点 {graphPreview.stats.node_count ?? '—'}
            </p>
          ) : null}
        </div>
      </div>

      {sketchOpen ? (
        <SketchModal
          onClose={() => setSketchOpen(false)}
          onConfirm={(data) => {
            setStrokeData(data)
            if (data.strokeMode === 'single_path') {
              setProcessedComponents([buildSinglePath(data.strokes)])
            } else {
              const comps = findConnectedComponents(data.strokes)
              setProcessedComponents(
                comps.map((indices) => buildSinglePath(indices.map((i) => data.strokes[i]))),
              )
            }
            setSketchOpen(false)
          }}
        />
      ) : null}
    </aside>
  )
}
