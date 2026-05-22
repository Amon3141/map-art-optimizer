import { useRef } from 'react'

export type BasemapMode = 'normal' | 'light' | 'dark'

const OPTIONS: { mode: BasemapMode; label: string }[] = [
  { mode: 'normal', label: '標準' },
  { mode: 'light', label: 'ライト' },
  { mode: 'dark', label: 'ダーク' },
]

const CLICK_COOLDOWN_MS = 1000

export type BasemapSelectorProps = {
  value: BasemapMode
  onChange: (mode: BasemapMode) => void
  className?: string
}

export function BasemapSelector({ value, onChange, className = '' }: BasemapSelectorProps) {
  const lastAcceptedAtRef = useRef(0)

  const handleSelect = (mode: BasemapMode) => {
    const now = performance.now()
    if (now - lastAcceptedAtRef.current < CLICK_COOLDOWN_MS) return
    lastAcceptedAtRef.current = now
    onChange(mode)
  }

  return (
    <div
      className={[
        'pointer-events-auto inline-flex w-fit max-w-[calc(100vw-1.5rem)] flex-wrap items-stretch gap-0.5 rounded-xl border border-dashed border-stone-400 bg-[#fdfbf7]/95 p-0.5 shadow-sm backdrop-blur-[2px] sm:max-w-none',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      role="radiogroup"
      aria-label="地図の表示モード"
    >
      {OPTIONS.map(({ mode, label }) => (
        <button
          key={mode}
          type="button"
          role="radio"
          aria-checked={value === mode}
          onClick={() => handleSelect(mode)}
          className={[
            'min-w-0 shrink rounded-[10px] px-2.5 py-2 text-xs font-medium transition-colors sm:px-3 sm:text-sm',
            value === mode
              ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner ring-1 ring-stone-200/80'
              : 'text-stone-600 hover:border-[#4a6f8a]/30 hover:bg-white/80 hover:text-stone-800',
          ].join(' ')}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
