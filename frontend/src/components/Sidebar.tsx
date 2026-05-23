import { useState } from 'react'
import { MdOutlineDraw } from 'react-icons/md'
import { Link } from 'react-router-dom'
import { RouteOrderPreview } from './RouteOrderPreview'
import { SketchPreview } from './SketchPreview'
import type { OptimizeApiResponse } from '../lib/optimizeTypes'
import type { Point } from '../lib/simplify'
import {
  DEFAULT_IGNORE_SOURCE_ROTATION,
  FETCH_RADIUS_MAX_M,
  FETCH_RADIUS_MIN_M,
  FETCH_RADIUS_STEP_M,
  SPEED_PRESET_META,
  type SpeedPreset,
} from '../lib/appDefaults'
import { LabelWithInfoHint } from './InfoHint'
import { isDevelopment, isProduction } from '../lib/appEnv'
import type { StrokeData } from '../lib/strokeTypes'

const FETCH_RADIUS_HINT =
  '都市部など道路が密な地域では2.0km以下をお勧めします'
const EXPLORATION_SETTINGS_HINT =
  '都市部だったり形が複雑だったりすると、表示されている時間より最大10秒程度長くかかることがあります'
const LOCK_ROTATION_HINT =
  'ON のときは、描いた形の向きをおおよそ保ったままルートを探します。OFF のときは、回転も含めあらゆる向きから探します'

export type OptimizeState =
  | { kind: 'idle' }
  | {
      kind: 'running'
      startedAt: number
      preset: SpeedPreset
      centerLon: number
      centerLat: number
      fetchRadiusM: number
    }
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
  fetchRadiusM: number
  onFetchRadiusChange: (radiusM: number) => void
  onExplorationSettingsChange?: () => void
  onOptimize: (preset: SpeedPreset, ignoreSourceRotation: boolean) => void
}

export function Sidebar({
  targetKm,
  onTargetKmChange,
  strokeData,
  processedComponents,
  onOpenSketch,
  optimizeState,
  speedPreset,
  onSpeedPresetChange,
  fetchRadiusM,
  onFetchRadiusChange,
  onExplorationSettingsChange,
  onOptimize,
}: SidebarProps) {
  const [lockRotation, setLockRotation] = useState(!DEFAULT_IGNORE_SOURCE_ROTATION)
  const [previewMode, setPreviewMode] = useState<'shape' | 'order'>('order')

  const hasShape = Boolean(strokeData && strokeData.strokes.some((s) => s.length >= 2))
  const isRunning = optimizeState.kind === 'running'
  const result = optimizeState.kind === 'done' ? optimizeState.result : null

  function handleOptimize() {
    if (!hasShape || isRunning) return
    onOptimize(speedPreset, !lockRotation)
  }

  const canShowOrderPreview = Boolean(processedComponents && processedComponents.length > 0)
  const showPreview = hasShape && strokeData

  const previewContent =
    showPreview && canShowOrderPreview && previewMode === 'order' ? (
      <RouteOrderPreview paths={processedComponents!} className="h-full w-full" />
    ) : showPreview ? (
      <SketchPreview strokes={strokeData!.strokes} className="h-full w-full" />
    ) : null

  return (
    <aside className="scrollbar-hidden flex w-full shrink-0 flex-col gap-4 p-5 pb-4 max-lg:overflow-visible lg:h-full lg:max-w-sm lg:min-h-0 lg:overflow-hidden lg:py-5 lg:pl-5 lg:pr-0">
      <div className="flex shrink-0 flex-col gap-1.5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">GPSアート作成機</h1>
        <p className="text-sm leading-relaxed text-stone-600">
          キャンバスに描いた形を、地図の道路上で再現するルートを探します。
        </p>
      </div>

      <button
        type="button"
        className="inline-flex shrink-0 items-center justify-center gap-1 rounded-xl border border-dashed border-stone-400 bg-white py-3 text-sm font-medium text-stone-800 shadow-sm hover:border-[#4a6f8a] hover:bg-[#f3f6f8]"
        onClick={onOpenSketch}
      >
        <MdOutlineDraw className="h-5 w-5 shrink-0 text-stone-700" aria-hidden />
        {hasShape ? '形を描き直す' : '形を描く'}
      </button>

      {showPreview && canShowOrderPreview ? (
        <div className="flex shrink-0 rounded-lg border border-stone-200 bg-stone-100 p-0.5 text-xs">
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
      ) : null}

      {showPreview ? (
        <div className="flex min-h-0 min-w-0 justify-center overflow-hidden max-lg:contents lg:flex-1">
          <div className="mx-auto aspect-square w-full max-w-[min(100%,360px)] shrink-0 overflow-hidden lg:min-h-0 lg:min-w-0 lg:max-h-full lg:max-w-none">
            {previewContent}
          </div>
        </div>
      ) : null}

      <div className="flex shrink-0 flex-col gap-3.5 lg:mt-auto">
        <div className="flex flex-col gap-1.5">
          <LabelWithInfoHint
            label="探索設定"
            hintLabel="探索設定について"
            className="text-sm text-stone-700"
          >
            {EXPLORATION_SETTINGS_HINT}
          </LabelWithInfoHint>
          <div className="grid grid-cols-3 gap-1.5">
            {(Object.keys(SPEED_PRESET_META) as SpeedPreset[]).map((p) => (
              <button
                key={p}
                type="button"
                disabled={isRunning}
                className={`rounded-xl border py-2 text-center transition-colors disabled:opacity-50 ${
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
        </div>
        

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between text-sm text-stone-700">
            <LabelWithInfoHint label="探索範囲" hintLabel="探索範囲の目安">
              {FETCH_RADIUS_HINT}
            </LabelWithInfoHint>
            <span className="tabular-nums text-stone-600">
              {(fetchRadiusM / 1000).toFixed(1)} km
            </span>
          </div>
          <input
            type="range"
            min={FETCH_RADIUS_MIN_M}
            max={FETCH_RADIUS_MAX_M}
            step={FETCH_RADIUS_STEP_M}
            value={fetchRadiusM}
            disabled={isRunning}
            onChange={(e) => onFetchRadiusChange(Number(e.target.value))}
            className="w-full accent-[#4a6f8a] disabled:opacity-50"
            aria-label="道路データの探索範囲"
          />
        </div>

        <div className="flex items-center justify-between text-sm text-stone-700">
          <LabelWithInfoHint label="形の向きを保つ" hintLabel="形の向きを保つについて">
            {LOCK_ROTATION_HINT}
          </LabelWithInfoHint>
          <button
            type="button"
            role="switch"
            aria-checked={lockRotation}
            aria-label="形の向きを保つ"
            disabled={isRunning}
            className="shrink-0 disabled:opacity-50"
            onClick={() => {
              setLockRotation((v) => !v)
              onExplorationSettingsChange?.()
            }}
          >
            <span
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
      </div>

      {!isProduction ? (
        <div className="flex shrink-0 flex-col gap-2">
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
      ) : null}

      <button
        type="button"
        disabled={!hasShape || isRunning}
        className="shrink-0 rounded-xl bg-[#c45c3e] py-3 text-sm font-semibold text-white shadow-md hover:bg-[#b14f33] disabled:cursor-not-allowed disabled:opacity-50"
        onClick={handleOptimize}
      >
        {isRunning ? '探索中…' : result ? 'もう一度探す' : 'GPSアートを作成'}
      </button>

      {isDevelopment ? (
        <Link
          to="/debug"
          className="shrink-0 text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline max-lg:mt-auto"
        >
          デバッグページへ →
        </Link>
      ) : null}

    </aside>
  )
}
