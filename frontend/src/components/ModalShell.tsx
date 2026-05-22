import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { MODAL_Z_INDEX, MODAL_Z_INDEX_STACKED } from '../lib/modalLayers'

export type ModalLayout = 'center' | 'sheet'
export type ModalBackdrop = 'default' | 'light'

export type ModalShellProps = {
  open: boolean
  layout: ModalLayout
  onClose?: () => void
  closeOnBackdropClick?: boolean
  closeOnEscape?: boolean
  ariaLabelledBy?: string
  backdrop?: ModalBackdrop
  /** 前面に出す場合は stacked（確認ダイアログ等） */
  stacked?: boolean
  overlayClassName?: string
  backdropClassName?: string
  children: ReactNode
}

const BACKDROP_CLASS: Record<ModalBackdrop, string> = {
  default: 'bg-stone-900/40',
  light: 'bg-stone-900/25 sm:backdrop-blur-xs',
}

const LAYOUT_CLASS: Record<ModalLayout, string> = {
  center: 'items-center justify-center p-4',
  sheet: 'items-end justify-center sm:items-center sm:p-4',
}

export function ModalShell({
  open,
  layout,
  onClose,
  closeOnBackdropClick = true,
  closeOnEscape = true,
  ariaLabelledBy,
  backdrop = 'default',
  stacked = false,
  overlayClassName = '',
  backdropClassName = '',
  children,
}: ModalShellProps) {
  const zIndex = stacked ? MODAL_Z_INDEX_STACKED : MODAL_Z_INDEX

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open || !closeOnEscape || !onClose) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, closeOnEscape, onClose])

  if (!open) return null

  const overlay = (
    <div
      className={[
        'fixed inset-0 flex',
        LAYOUT_CLASS[layout],
        overlayClassName,
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ zIndex }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={ariaLabelledBy}
    >
      {onClose && closeOnBackdropClick ? (
        <button
          type="button"
          aria-label="閉じる"
          className={['absolute inset-0', BACKDROP_CLASS[backdrop], backdropClassName]
            .filter(Boolean)
            .join(' ')}
          onClick={onClose}
        />
      ) : (
        <div
          className={['absolute inset-0', BACKDROP_CLASS[backdrop], backdropClassName]
            .filter(Boolean)
            .join(' ')}
          aria-hidden
        />
      )}
      <div
        className={[
          'relative z-10 flex w-full flex-col items-center pointer-events-none [&>*]:pointer-events-auto',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {children}
      </div>
    </div>
  )

  return createPortal(overlay, document.body)
}
