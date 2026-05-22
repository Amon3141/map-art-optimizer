import { useEffect, useState } from 'react'
import { MdOutlineDraw } from 'react-icons/md'
import { Link } from 'react-router-dom'
import { RouteOrderPreview } from './RouteOrderPreview'
import { SketchPreview } from './SketchPreview'
import type { OptimizeApiResponse } from '../lib/optimizeTypes'
import type { Point } from '../lib/simplify'
import {
  DEFAULT_IGNORE_SOURCE_ROTATION,
  SPEED_PRESET_META,
  type SpeedPreset,
} from '../lib/productionDefaults'
import type { StrokeData } from '../lib/strokeTypes'

export type OptimizeState =
  | { kind: 'idle' }
  | { kind: 'running'; startedAt: number; preset: SpeedPreset }
  | { kind: 'done'; result: OptimizeApiResponse }
  | { kind: 'error'; message: string }

export type SidebarProps = {
  targetKm: number
  onTargetKmChange: (km: number) => void
  strokeData: StrokeData | null
  processedComponents: Point[][] | null
  onOpenSketch: () => void
  optimizeState: OptimizeState
  speedPreset: SpeedPreset
  onSpeedPresetChange: (p: SpeedPreset) => void
  onOptimize: (preset: SpeedPreset, ignoreSourceRotation: boolean) => void
}

const showDebugNav = import.meta.env.VITE_DEBUG === 'true'

export function Sidebar({
  targetKm,
  onTargetKmChange,
  strokeData,
  processedComponents,
  onOpenSketch,
  optimizeState,
  speedPreset,
  onSpeedPresetChange,
  onOptimize,
}: SidebarProps) {
  const [lockRotation, setLockRotation] = useState(!DEFAULT_IGNORE_SOURCE_ROTATION)
  const [previewMode, setPreviewMode] = useState<'shape' | 'order'>('shape')

  const hasShape = Boolean(strokeData && strokeData.strokes.some((s) => s.length >= 2))
  const isRunning = optimizeState.kind === 'running'
  const result = optimizeState.kind === 'done' ? optimizeState.result : null

  // 結果が届いたら巡回順表示に切り替え
  useEffect(() => {
    if (optimizeState.kind === 'done') {
      setPreviewMode('order')
    }
  }, [optimizeState.kind])

  function handleOptimize() {
    if (!hasShape || isRunning) return
    onOptimize(speedPreset, !lockRotation)
  }

  const canShowOrderPreview = Boolean(processedComponents && processedComponents.length > 0)

  return (
    <aside className="flex w-full shrink-0 flex-col gap-4 overflow-y-auto p-5 pb-4 lg:max-w-sm lg:py-5 lg:pl-5 lg:pr-0">
      {/* タイトル */}
      <div className="flex flex-col gap-1.5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">GPSアート作成機</h1>
        <p className="text-sm leading-relaxed text-stone-600">
          キャンバスに描いた形を、地図の道路上で再現するルートを探します。
        </p>
      </div>

      {/* スケッチ入力 */}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1 rounded-xl border border-dashed border-stone-400 bg-white py-3 text-sm font-medium text-stone-800 shadow-sm hover:border-[#4a6f8a] hover:bg-[#f3f6f8]"
          onClick={onOpenSketch}
        >
          <MdOutlineDraw className="h-5 w-5 shrink-0 text-stone-700" aria-hidden />
          {hasShape ? '形を描き直す' : '形を描く'}
        </button>

        {hasShape && strokeData ? (
          <div className="flex flex-col gap-2">
            {/* プレビューモード切り替え（結果あり時のみ） */}
            {result && canShowOrderPreview && (
              <div className="flex rounded-lg border border-stone-200 bg-stone-100 p-0.5 text-xs">
                <button
                  type="button"
                  className={`flex-1 rounded-md py-1.5 text-center transition-colors ${
                    previewMode === 'shape'
                      ? 'bg-white font-medium text-stone-800 shadow-sm'
                      : 'text-stone-500 hover:text-stone-700'
                  }`}
                  onClick={() => setPreviewMode('shape')}
                >
                  もとの形
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-md py-1.5 text-center transition-colors ${
                    previewMode === 'order'
                      ? 'bg-white font-medium text-stone-800 shadow-sm'
                      : 'text-stone-500 hover:text-stone-700'
                  }`}
                  onClick={() => setPreviewMode('order')}
                >
                  巡回順
                </button>
              </div>
            )}

            {/* プレビュー本体 */}
            {result && canShowOrderPreview && previewMode === 'order' ? (
              <RouteOrderPreview
                paths={processedComponents!}
                className="aspect-square mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
              />
            ) : (
              <SketchPreview
                strokes={strokeData.strokes}
                className="aspect-square mx-auto w-full max-w-[220px] lg:mx-0 lg:max-w-none"
              />
            )}
          </div>
        ) : null}
      </div>

      {/* 探索設定 */}
      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium text-stone-700">探索設定</p>

        {/* 速度プリセット */}
        <div className="grid grid-cols-3 gap-1.5">
          {(Object.keys(SPEED_PRESET_META) as SpeedPreset[]).map((p) => (
            <button
              key={p}
              type="button"
              className={`rounded-xl border py-2 text-center transition-colors ${
                speedPreset === p
                  ? 'border-[#4a6f8a] bg-[#4a6f8a] text-white'
                  : 'border-stone-200 bg-white text-stone-700 hover:border-stone-300'
              }`}
              onClick={() => onSpeedPresetChange(p)}
            >
              <div className="text-xs font-semibold">{SPEED_PRESET_META[p].label}</div>
              <div className={`text-[10px] ${speedPreset === p ? 'text-white/75' : 'text-stone-400'}`}>
                {SPEED_PRESET_META[p].description}
              </div>
            </button>
          ))}
        </div>

        {/* 回転固定トグル */}
        <button
          type="button"
          className="flex items-center justify-between text-sm text-stone-700"
          onClick={() => setLockRotation((v) => !v)}
        >
          <span>向きを固定する</span>
          <span
            role="switch"
            aria-checked={lockRotation}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              lockRotation ? 'bg-[#4a6f8a]' : 'bg-stone-300'
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 translate-y-0 rounded-full bg-white shadow transition-transform ${
                lockRotation ? 'translate-x-[18px]' : 'translate-x-[2px]'
              }`}
            />
          </span>
        </button>
      </div>

      {/* 距離の目安 */}
      <div className="flex flex-col gap-2">
        <label className="block text-sm font-medium text-stone-700">
          距離の目安（km）
          <input
            type="number"
            min={1}
            step={1}
            value={Number.isFinite(targetKm) ? targetKm : 1}
            onChange={(e) => onTargetKmChange(Math.max(1, parseInt(e.target.value, 10) || 1))}
            className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-stone-900 shadow-inner outline-none ring-[#4a6f8a] focus:ring-2"
          />
        </label>
      </div>

      {/* アクションボタン */}
      <button
        type="button"
        disabled={!hasShape || isRunning}
        className="rounded-xl bg-[#c45c3e] py-3 text-sm font-semibold text-white shadow-md hover:bg-[#b14f33] disabled:cursor-not-allowed disabled:opacity-50"
        onClick={handleOptimize}
      >
        {isRunning ? '探索中…' : result ? 'もう一度探す' : 'GPSアートを作成'}
      </button>

      {/* エラー表示 */}
      {optimizeState.kind === 'error' && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700">
          {optimizeState.message}
        </div>
      )}

      {showDebugNav ? (
        <Link
          to="/debug"
          className="mt-auto text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline"
        >
          デバッグページへ →
        </Link>
      ) : null}
    </aside>
  )
}
