import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'

const TOOLTIP_Z_INDEX = 40
const GAP_PX = 6

function prefersHover(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(hover: hover)').matches
}

export type InfoHintProps = {
  label: string
  children: ReactNode
}

export function InfoHint({ label, children }: InfoHintProps) {
  const tooltipId = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [visible, setVisible] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  const updatePosition = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setPos({
      top: rect.top + rect.height / 2,
      left: rect.right + GAP_PX,
    })
  }, [])

  useLayoutEffect(() => {
    if (!visible) return
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [visible, updatePosition])

  useEffect(() => {
    if (!visible || prefersHover()) return
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target
      if (!(target instanceof Node)) return
      if (triggerRef.current?.contains(target)) return
      const tip = document.getElementById(tooltipId)
      if (tip?.contains(target)) return
      setVisible(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [visible, tooltipId])

  const tooltip =
    visible &&
    createPortal(
      <div
        id={tooltipId}
        role="tooltip"
        className="fixed w-max max-w-[min(16rem,calc(100vw-2rem))] rounded-lg border border-stone-200 bg-white px-2.5 py-2 text-xs leading-relaxed text-stone-700 shadow-md"
        style={{
          top: pos.top,
          left: pos.left,
          zIndex: TOOLTIP_Z_INDEX,
          transform: 'translateY(-50%)',
        }}
      >
        {children}
      </div>,
      document.body,
    )

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-200 text-[10px] font-bold leading-none text-amber-900 shadow-sm outline-none ring-[#4a6f8a]/40 focus-visible:ring-2 [@media(hover:hover)]:hover:bg-amber-300"
        aria-label={label}
        aria-expanded={visible}
        aria-describedby={visible ? tooltipId : undefined}
        onMouseEnter={() => {
          if (prefersHover()) setVisible(true)
        }}
        onMouseLeave={() => {
          if (prefersHover()) setVisible(false)
        }}
        onClick={() => {
          if (!prefersHover()) setVisible((v) => !v)
        }}
      >
        i
      </button>
      {tooltip}
    </>
  )
}

export type LabelWithInfoHintProps = {
  label: string
  hintLabel: string
  children: ReactNode
  className?: string
}

/** ラベル文字列の右に InfoHint を並べる */
export function LabelWithInfoHint({
  label,
  hintLabel,
  children,
  className = '',
}: LabelWithInfoHintProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 font-medium ${className}`.trim()}>
      {label}
      <InfoHint label={hintLabel}>{children}</InfoHint>
    </span>
  )
}
