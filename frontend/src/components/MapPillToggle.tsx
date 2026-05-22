export type MapPillToggleProps = {
  value: boolean
  onChange: (value: boolean) => void
  offLabel: string
  onLabel: string
  ariaLabel: string
}

export function MapPillToggle({
  value,
  onChange,
  offLabel,
  onLabel,
  ariaLabel,
}: MapPillToggleProps) {
  return (
    <div
      className="pointer-events-auto inline-flex w-fit shrink-0 flex-nowrap items-stretch gap-0 rounded-full border border-dashed border-stone-400 bg-[#fdfbf7]/95 p-0.5 shadow-sm backdrop-blur-[2px]"
      role="radiogroup"
      aria-label={ariaLabel}
    >
      <button
        type="button"
        role="radio"
        aria-checked={!value}
        onClick={() => onChange(false)}
        className={[
          'min-w-0 shrink rounded-l-full px-2.5 py-2 text-xs font-medium transition-colors sm:px-3 sm:text-sm',
          !value
            ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner ring-1 ring-stone-200/80'
            : 'text-stone-600 hover:border-[#4a6f8a]/30 hover:bg-white/80 hover:text-stone-800',
        ].join(' ')}
      >
        {offLabel}
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={value}
        onClick={() => onChange(true)}
        className={[
          'min-w-0 shrink rounded-r-full px-2.5 py-2 text-xs font-medium transition-colors sm:px-3 sm:text-sm',
          value
            ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner ring-1 ring-stone-200/80'
            : 'text-stone-600 hover:border-[#4a6f8a]/30 hover:bg-white/80 hover:text-stone-800',
        ].join(' ')}
      >
        {onLabel}
      </button>
    </div>
  )
}
