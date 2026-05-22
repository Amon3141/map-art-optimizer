import { useEffect, useState } from 'react'
import type { SpeedPreset } from '../lib/productionDefaults'
import { PRESET_BUDGET_S } from '../lib/productionDefaults'

const STEPS = [
  { label: '道路データを取得中', minSeconds: 0 },
  { label: '道路グラフを構築中', minSeconds: 3 },
  { label: 'ルートを探索中', minSeconds: 6 },
] as const

type Props = {
  visible: boolean
  startedAt: number | null
  preset: SpeedPreset
}

/** 地図上に重なるステータス表示オーバーレイ。最適化実行中に表示する。 */
export function OptimizeStatusOverlay({ visible, startedAt, preset }: Props) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!visible || startedAt == null) {
      setElapsed(0)
      return
    }
    const update = () => setElapsed((Date.now() - startedAt) / 1000)
    update()
    const id = window.setInterval(update, 200)
    return () => window.clearInterval(id)
  }, [visible, startedAt])

  if (!visible) return null

  const currentStep = STEPS.reduce<(typeof STEPS)[number]>(
    (acc, step) => (elapsed >= step.minSeconds ? step : acc),
    STEPS[0],
  )

  const budget = PRESET_BUDGET_S[preset]
  const totalSeconds = budget + 6
  const progress = Math.min(elapsed / totalSeconds, 0.97)

  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
      <div className="mx-4 w-full max-w-xs rounded-2xl border border-stone-200 bg-white/95 px-5 py-4 shadow-xl backdrop-blur-sm">
        <div className="mb-3 flex items-center gap-2.5">
          <span className="relative flex size-3 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#c45c3e] opacity-60" />
            <span className="relative inline-flex size-3 rounded-full bg-[#c45c3e]" />
          </span>
          <span className="text-sm font-medium text-stone-800">{currentStep.label}…</span>
        </div>

        <div className="h-1.5 overflow-hidden rounded-full bg-stone-100">
          <div
            className="h-full rounded-full bg-[#c45c3e] transition-all duration-500"
            style={{ width: `${progress * 100}%` }}
          />
        </div>

        <p className="mt-2 text-right text-[11px] text-stone-400">
          {Math.round(elapsed)}s / {totalSeconds}s
        </p>
      </div>
    </div>
  )
}
