import { ModalShell } from './ModalShell'

export type FetchRadiusErrorDialogProps = {
  open: boolean
  message: string
  onClose: () => void
}

export function FetchRadiusErrorDialog({ open, message, onClose }: FetchRadiusErrorDialogProps) {
  if (!open) return null

  return (
    <ModalShell
      open
      layout="center"
      backdrop="default"
      stacked
      onClose={onClose}
      ariaLabelledBy="fetch-radius-error-title"
    >
      <div className="w-full max-w-md rounded-2xl border border-stone-200/80 bg-[#faf8f4] p-5 shadow-xl">
        <h2 id="fetch-radius-error-title" className="text-lg font-semibold text-stone-800">
          探索範囲を小さくしてください
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-stone-600">{message}</p>
        <div className="mt-5 flex flex-row justify-end">
          <button
            type="button"
            className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-semibold text-white shadow-md hover:bg-[#3d5f78]"
            onClick={onClose}
          >
            OK
          </button>
        </div>
      </div>
    </ModalShell>
  )
}
