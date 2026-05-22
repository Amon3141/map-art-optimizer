import type { OptimizeTraceStep } from '../lib/optimizeTypes'

export type AnnealingTraceSliderProps = {
  steps: OptimizeTraceStep[]
  /** 省略時はキャプションに非表示 */
  bestRestartIndex?: number
  /** 省略時はキャプションに非表示 */
  selectedRestartIndex?: number
  showBestRoute: boolean
  onShowBestRoute: () => void
  selectedTraceIndex: number
  traceSliderValue: number
  onTraceSliderChange: (index: number) => void
  /** showBestRoute=true のときのボタン文字列（デフォルト: 'ベスト候補を表示中'） */
  showBestLabel?: string
  /** showBestRoute=false のときのボタン文字列（デフォルト: 'ベスト候補に戻す'） */
  returnToBestLabel?: string
}

export function AnnealingTraceSlider({
  steps,
  bestRestartIndex,
  selectedRestartIndex,
  showBestRoute,
  onShowBestRoute,
  selectedTraceIndex,
  traceSliderValue,
  onTraceSliderChange,
  showBestLabel = 'ベスト候補を表示中',
  returnToBestLabel = 'ベスト候補に戻す',
}: AnnealingTraceSliderProps) {
  const maxStepIdx = Math.max(0, steps.length - 1)
  const displayStep = showBestRoute ? null : steps[selectedTraceIndex]
  const fillColor = showBestRoute ? '#fbbf24' : '#4a6f8a'
  const fillPct = maxStepIdx > 0 ? (traceSliderValue / maxStepIdx) * 100 : 0
  const sliderStyle = {
    '--trace-fill': fillColor,
    '--trace-track': '#e7e5e4',
    '--trace-pct': `${fillPct}%`,
  } as React.CSSProperties

  return (
    <>
      <div className="mt-2 mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-stone-700">トレース表示</span>
        <button
          type="button"
          className={`text-[11px] font-medium ${showBestRoute ? 'cursor-default text-amber-500' : 'text-[#4a6f8a] hover:underline'}`}
          onClick={onShowBestRoute}
        >
          {showBestRoute ? showBestLabel : returnToBestLabel}
        </button>
      </div>
      {steps.length === 0 ? (
        <p className="text-[11px] leading-snug text-stone-500">この試行のトレースがありません。</p>
      ) : maxStepIdx === 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-[11px] leading-snug text-stone-500">
            トレースは 1 ステップのみです。必要なら下のボタンで地図に重ねられます。
          </p>
          <button
            type="button"
            className="rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-[11px] font-medium text-stone-800 hover:bg-stone-50"
            onClick={() => onTraceSliderChange(0)}
          >
            このステップを地図に表示
          </button>
        </div>
      ) : (
        <input
          id="trace-slider"
          type="range"
          min={0}
          max={maxStepIdx}
          value={traceSliderValue}
          onChange={(e) => onTraceSliderChange(Number(e.target.value))}
          style={sliderStyle}
          className={[
            'h-6 w-full cursor-pointer appearance-none bg-transparent',
            '[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full',
            '[&::-webkit-slider-runnable-track]:bg-[linear-gradient(to_right,var(--trace-fill)_0%,var(--trace-fill)_var(--trace-pct),var(--trace-track)_var(--trace-pct),var(--trace-track)_100%)]',
            '[&::-webkit-slider-thumb]:-mt-1 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5',
            '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white',
            '[&::-webkit-slider-thumb]:bg-(--trace-fill) [&::-webkit-slider-thumb]:shadow-sm',
            '[&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-(--trace-track)',
            '[&::-moz-range-progress]:h-1.5 [&::-moz-range-progress]:rounded-full [&::-moz-range-progress]:bg-(--trace-fill)',
            '[&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white',
            '[&::-moz-range-thumb]:bg-(--trace-fill) [&::-moz-range-thumb]:shadow-sm',
          ].join(' ')}
        />
      )}
      <p className={`font-mono text-[10px] ${showBestRoute ? 'text-amber-500' : 'text-stone-500'}`}>
        {showBestRoute ? (
          bestRestartIndex != null ? (
            <>{showBestLabel}（試行 #{bestRestartIndex}）</>
          ) : (
            <>{showBestLabel}</>
          )
        ) : displayStep ? (
          selectedRestartIndex != null ? (
            <>
              試行 #{selectedRestartIndex} · トレース {selectedTraceIndex + 1}/{steps.length} · step{' '}
              {displayStep.step_index} · score={displayStep.score_total.toFixed(4)}
            </>
          ) : (
            <>
              ステップ {selectedTraceIndex + 1}/{steps.length} · score=
              {displayStep.score_total.toFixed(4)}
            </>
          )
        ) : null}
      </p>
    </>
  )
}
