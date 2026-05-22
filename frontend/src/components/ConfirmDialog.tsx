import { ModalShell } from './ModalShell'

export type StopOptimizeConfirmVariant = 'sketch' | 'overlay'

const STOP_OPTIMIZE_CONFIRM_COPY: Record<
  StopOptimizeConfirmVariant,
  { title: string; message: string; confirmLabel: string; cancelLabel: string }
> = {
  sketch: {
    title: '探索を止めて形を変えますか？',
    message: '形を編集するには、進行中の探索を止めてください。',
    cancelLabel: '続ける',
    confirmLabel: '止めて形を変える',
  },
  overlay: {
    title: '探索を止めますか？',
    message: '進行中のルート探索を中断します。',
    cancelLabel: '続ける',
    confirmLabel: '停止',
  },
}

export type ConfirmDialogProps = {
  open: boolean
  variant: StopOptimizeConfirmVariant | null
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ open, variant, onConfirm, onCancel }: ConfirmDialogProps) {
  if (!open || variant == null) return null

  const { title, message, confirmLabel, cancelLabel } = STOP_OPTIMIZE_CONFIRM_COPY[variant]

  return (
    <ModalShell
      open
      layout="center"
      backdrop="default"
      stacked
      onClose={onCancel}
      ariaLabelledBy="confirm-dialog-title"
    >
      <div className="w-full max-w-md rounded-2xl border border-stone-200/80 bg-[#faf8f4] p-5 shadow-xl">
        <h2 id="confirm-dialog-title" className="text-lg font-semibold text-stone-800">
          {title}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-stone-600">{message}</p>
        <div className="mt-5 flex flex-row justify-end gap-2">
          <button
            type="button"
            className="rounded-xl border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-700 hover:bg-stone-50"
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="rounded-xl bg-[#c45c3e] px-4 py-2.5 text-sm font-semibold text-white shadow-md hover:bg-[#b14f33]"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}
