import { useEffect, useMemo, useState } from 'react'
import { MdOutlineDraw } from 'react-icons/md'
import { SketchModal } from '../../components/SketchModal'
import { SketchPreview } from '../../components/SketchPreview'
import { apiUrl } from '../../lib/api'
import type { Point } from '../../lib/simplify'
import {
  normalizeGraphBuildOptions,
  type GraphBuildOptionsPayload,
  type GraphPreviewResponse,
} from '../lib/graphPreview'
import {
  DEFAULT_ANNEAL_SEED,
  DEFAULT_COARSE_PRESOLVE,
  DEFAULT_COARSE_SCALE_BINS,
  DEFAULT_COARSE_THETA_BINS,
  DEFAULT_EVALUATION_MODE,
  DEFAULT_INCLUDE_MIRROR_STROKE,
  DEFAULT_NUM_RESTARTS,
  DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
} from '../lib/optimizationDefaults'
import { rebuildRouteFeatureCollection } from '../lib/rebuildRouteFromTraceStep'

export type OptimizeTraceStep = {
  step_index: number
  temperature: number
  accepted: boolean
  score_total: number
  score_terms: Record<string, number>
  transform: Record<string, number>
  edge_ids: string[]
}

type EvaluationMode = 'faithful' | 'elegant'

export type OptimizeApiResponse = {
  trace_format_version: number
  projection: GraphPreviewResponse['projection']
  projection_summary?: string
  stats: Record<string, number>
  candidates_geojson: GeoJSON.FeatureCollection
  best_score: number
  best_breakdown: Record<string, number>
  /** ベストルートのグラフ上の長さ（メートル） */
  route_length_m?: number
  /** 同上（キロメートル）。評価とは独立した表示用メタ情報 */
  route_length_km?: number
  optimizer_meta?: Record<string, unknown>
  steps: OptimizeTraceStep[]
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

export function DebugOptimizePanel({
  geojson,
  graphOptions,
  graphPreview,
  onBack,
  getMapBounds,
  onRouteOverlayChange,
}: DebugOptimizePanelProps) {
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokePoints, setStrokePoints] = useState<Point[] | null>(null)
  const [seed, setSeed] = useState(DEFAULT_ANNEAL_SEED)
  const [budgetSeconds, setBudgetSeconds] = useState(DEFAULT_OPTIMIZATION_BUDGET_SECONDS)
  const [numRestarts, setNumRestarts] = useState(DEFAULT_NUM_RESTARTS)
  const [includeMirrorStroke, setIncludeMirrorStroke] = useState(DEFAULT_INCLUDE_MIRROR_STROKE)
  const [coarsePresolve, setCoarsePresolve] = useState(DEFAULT_COARSE_PRESOLVE)
  const [coarseThetaBins, setCoarseThetaBins] = useState(DEFAULT_COARSE_THETA_BINS)
  const [coarseScaleBins, setCoarseScaleBins] = useState(DEFAULT_COARSE_SCALE_BINS)
  const [evaluationMode, setEvaluationMode] = useState<EvaluationMode>(DEFAULT_EVALUATION_MODE as EvaluationMode)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<OptimizeApiResponse | null>(null)
  /** 'best' = API の candidates_geojson、数値 = steps のインデックス */
  const [traceView, setTraceView] = useState<'best' | number>('best')

  const optsNorm = useMemo(() => normalizeGraphBuildOptions(graphOptions), [graphOptions])

  const hasShape = Boolean(strokePoints && strokePoints.length >= 2)
  const steps = result?.steps ?? []
  const maxStepIdx = Math.max(0, steps.length - 1)

  useEffect(() => {
    if (!result) {
      onRouteOverlayChange(null)
      return
    }
    if (traceView === 'best') {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    const edges = graphPreview?.graph_geojson?.edges
    if (!edges) {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    const step = result.steps[traceView]
    if (!step) {
      onRouteOverlayChange(result.candidates_geojson)
      return
    }
    onRouteOverlayChange(rebuildRouteFeatureCollection(step.edge_ids, edges))
  }, [result, traceView, graphPreview, onRouteOverlayChange])

  const runOptimize = async () => {
    if (!geojson?.features?.length || !strokePoints || strokePoints.length < 2) {
      setError('道路データ・手書きの形の両方が必要です。')
      return
    }
    const bbox = getMapBounds()
    if (!bbox) {
      setError('地図の範囲を取得できませんでした。')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const body = {
        geojson,
        bbox,
        options: optsNorm,
        stroke_points: strokePoints.map((p) => ({ x: p.x, y: p.y })),
        record_trace: true,
        anneal: {
          optimization_budget_seconds: budgetSeconds,
          seed,
          num_restarts: numRestarts,
          include_mirror_stroke: includeMirrorStroke,
          coarse_presolve: coarsePresolve,
          coarse_theta_bins: coarseThetaBins,
          coarse_scale_bins: coarseScaleBins,
          evaluation_mode: evaluationMode,
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
      setTraceView('best')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const displayStep = traceView === 'best' ? null : steps[traceView]

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
          現在のグラフと表示範囲をそのまま使い、手書きの形に近い道路ルートを<strong>離散グリッド</strong>
          （回転・スケール・並進の総当たり）で選びます。辺数が多い bbox は前処理で範囲を絞ると応答が安定します。
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
            {hasShape && strokePoints ? (
              <SketchPreview
                points={strokePoints}
                className="mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
              />
            ) : null}
          </div>

          <details className="rounded-lg border border-stone-200/80 bg-stone-50/50 p-2">
            <summary className="cursor-pointer text-xs py-0.5 font-medium text-stone-700">グリッド探索の設定</summary>
            <div className="mt-2.5 flex flex-col gap-2">
              <label className="text-xs text-stone-600">
                評価モード
                <select
                  value={evaluationMode}
                  onChange={(e) => setEvaluationMode(e.target.value as EvaluationMode)}
                  className="mt-0.5 w-full rounded border border-stone-200 bg-white px-2 py-1 text-sm"
                >
                  <option value="faithful">faithful（形状・角度重視）</option>
                  <option value="elegant">elegant（形状 + 簡潔さ）</option>
                </select>
              </label>
              <label className="text-xs text-stone-600">
                乱数シード（θ 位相の微調整に使用）
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value) || 0)}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                />
              </label>
              <label className="text-xs text-stone-600">
                最適化の時間上限（秒・サーバ側）
                <input
                  type="number"
                  min={0.05}
                  max={120}
                  step={0.5}
                  value={budgetSeconds}
                  onChange={(e) => setBudgetSeconds(Math.min(120, Math.max(0.05, Number(e.target.value) || 10)))}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                />
              </label>
              <label className="text-xs text-stone-600">
                リスタート回数（θ 位相オフセット）
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={numRestarts}
                  onChange={(e) => setNumRestarts(Math.min(64, Math.max(1, Number(e.target.value) || 1)))}
                  className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                />
              </label>
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-stone-700">
                <input
                  type="checkbox"
                  className="size-4 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
                  checked={coarsePresolve}
                  onChange={(e) => setCoarsePresolve(e.target.checked)}
                />
                <span>離散グリッドで探索（オフのときは恒等変換のみ評価）</span>
              </label>
              {coarsePresolve ? (
                <div className="ml-6 flex flex-col gap-2 border-l border-stone-200 pl-2">
                  <p className="text-[11px] leading-snug text-stone-500">
                    並進オフセット数点 ×{' '}
                    <span className="font-mono">[0, 2π)</span> の θ 等分 × スケール区間{' '}
                    <span className="font-mono">[0.75, 1.35]</span> の等分割を総当たりし、スコア最小の変換とルートを選びます。
                  </p>
                  <label className="text-xs text-stone-600">
                    θ の分割数（bins）
                    <input
                      type="number"
                      min={2}
                      max={64}
                      value={coarseThetaBins}
                      onChange={(e) => setCoarseThetaBins(Math.min(64, Math.max(2, Number(e.target.value) || 3)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="text-xs text-stone-600">
                    スケールの分割数（bins）
                    <input
                      type="number"
                      min={1}
                      max={32}
                      value={coarseScaleBins}
                      onChange={(e) => setCoarseScaleBins(Math.min(32, Math.max(1, Number(e.target.value) || 3)))}
                      className="mt-0.5 w-full rounded border border-stone-200 px-2 py-1 text-sm"
                    />
                  </label>
                </div>
              ) : null}
              <label className="flex cursor-pointer items-center gap-2 text-xs text-stone-700">
                <input
                  type="checkbox"
                  className="size-4 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
                  checked={includeMirrorStroke}
                  onChange={(e) => setIncludeMirrorStroke(e.target.checked)}
                />
                <span>左右鏡映ストロークも試す</span>
              </label>
            </div>
          </details>

          <button
            type="button"
            disabled={loading || !hasShape}
            onClick={() => void runOptimize()}
            className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-50"
          >
            {loading ? '探索中…' : 'グリッド探索を実行'}
          </button>

          {error ? <p className="text-sm text-red-700">{error}</p> : null}

          {result ? (
            <div className="flex flex-col gap-3 border-t border-stone-200/80 pt-3">
              <div className="flex flex-col gap-1">
                <p className="text-xs text-stone-700">
                  ベストスコア: <span className="font-mono">{result.best_score.toFixed(4)}</span>
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
              {steps.length > 0 ? (
                <div className="mt-0.5">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-stone-700">トレース表示</span>
                    <button
                      type="button"
                      className="text-[11px] font-medium text-[#4a6f8a] hover:underline"
                      onClick={() => setTraceView('best')}
                    >
                      ベストに戻す
                    </button>
                  </div>
                  {maxStepIdx === 0 ? (
                    <p className="text-[11px] leading-snug text-stone-500">
                      トレースは 1 ステップのみです。中間のベスト更新が記録されていないため、スライダーは表示しません。
                    </p>
                  ) : (
                    <input
                      id="trace-slider"
                      type="range"
                      min={0}
                      max={maxStepIdx}
                      value={traceView === 'best' ? maxStepIdx : traceView}
                      onChange={(e) => setTraceView(Number(e.target.value))}
                      className="w-full accent-[#4a6f8a]"
                    />
                  )}
                  <p className="mt-1 font-mono text-[10px] text-stone-500">
                    {traceView === 'best' ? (
                      <>表示: ベスト候補（スライダーはベスト 1 ステップの確認用）</>
                    ) : displayStep ? (
                      <>
                        step {displayStep.step_index} · score={displayStep.score_total.toFixed(4)}
                      </>
                    ) : null}
                  </p>
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
          onConfirm={(pts) => {
            setStrokePoints(pts)
            setSketchOpen(false)
          }}
        />
      ) : null}
    </aside>
  )
}
