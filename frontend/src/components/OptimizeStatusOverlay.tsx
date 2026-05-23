import { useEffect, useState } from 'react'
import { MdStop } from 'react-icons/md'
import type { SpeedPreset } from '../lib/appDefaults'
import { PRESET_BUDGET_S } from '../lib/appDefaults'

const STEPS = [
  { label: '道路データを取得中', minSeconds: 0 },
  { label: '道路グラフを構築中', minSeconds: 5 },
  { label: 'ルートを探索中', minSeconds: 8 },
] as const

type RunningProps = {
  mode: 'running'
  startedAt: number
  preset: SpeedPreset
  onStop?: () => void
}

type ErrorProps = {
  mode: 'error'
  message: string
  onDismiss: () => void
}

type Props = RunningProps | ErrorProps

function computeProgress(elapsed: number, budgetS: number): number {
  if (elapsed <= 5) return (elapsed / 5) * 0.15
  if (elapsed <= 8) return 0.15 + ((elapsed - 5) / 3) * 0.1
  const saElapsed = elapsed - 8
  return Math.min(0.25 + 0.72 * (1 - Math.exp(-2.5 * saElapsed / budgetS)), 0.97)
}

function RunningOverlay({
  startedAt,
  preset,
  onStop,
}: {
  startedAt: number
  preset: SpeedPreset
  onStop?: () => void
}) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const update = () => setElapsed((Date.now() - startedAt) / 1000)
    update()
    const id = window.setInterval(update, 200)
    return () => window.clearInterval(id)
  }, [startedAt])

  const currentStep = STEPS.reduce<(typeof STEPS)[number]>(
    (acc, step) => (elapsed >= step.minSeconds ? step : acc),
    STEPS[0],
  )

  const budget = PRESET_BUDGET_S[preset]
  const progress = computeProgress(elapsed, budget)

  return (
    <>
      <div className="mb-3 flex items-center gap-2.5">
        <span className="relative flex size-3 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#c45c3e] opacity-60" />
          <span className="relative inline-flex size-3 rounded-full bg-[#c45c3e]" />
        </span>
        <span className="min-w-0 flex-1 text-sm font-medium text-stone-800">
          {currentStep.label}…
        </span>
        {onStop ? (
          <button
            type="button"
            title="探索を停止"
            aria-label="探索を停止"
            className="-mr-1 flex shrink-0 items-center justify-center rounded-full border border-stone-300 p-0.5 text-stone-400 transition-[border-color] [@media(hover:hover)]:border-transparent [@media(hover:hover)]:hover:border-stone-300"
            onClick={onStop}
          >
            <MdStop className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-stone-100">
        <div
          className="h-full rounded-full bg-[#c45c3e] transition-all duration-500"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      <p className="mt-2 text-right text-[11px] text-stone-400">
        {Math.round(progress * 100)}%
      </p>
    </>
  )
}

function ErrorOverlay({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <>
      <p className="text-sm leading-relaxed text-red-700">{message}</p>
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          className="rounded-xl bg-[#4a6f8a] px-4 py-2 text-sm font-semibold text-white shadow-md hover:bg-[#3d5f78]"
          onClick={onDismiss}
        >
          閉じる
        </button>
      </div>
    </>
  )
}

/** 地図上に重なるステータス表示オーバーレイ。探索実行中は進捗、失敗時はエラーを表示する。 */
export function OptimizeStatusOverlay(props: Props) {
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
      <div className="pointer-events-auto mx-4 w-full max-w-xs rounded-2xl border border-stone-200 bg-white/95 px-5 py-4 shadow-xl backdrop-blur-sm">
        {props.mode === 'running' ? (
          <RunningOverlay
            startedAt={props.startedAt}
            preset={props.preset}
            onStop={props.onStop}
          />
        ) : (
          <ErrorOverlay message={props.message} onDismiss={props.onDismiss} />
        )}
      </div>
    </div>
  )
}
