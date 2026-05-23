import { ModalShell } from './ModalShell'

const ABOUT_MODAL_TITLE_ID = 'about-modal-title'

export type AboutModalProps = {
  open: boolean
  onClose: () => void
}

export function AboutModal({ open, onClose }: AboutModalProps) {
  return (
    <ModalShell
      open={open}
      layout="center"
      onClose={onClose}
      closeOnBackdropClick
      closeOnEscape
      ariaLabelledBy={ABOUT_MODAL_TITLE_ID}
    >
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
        <h2 id={ABOUT_MODAL_TITLE_ID} className="mb-4 text-base font-semibold text-stone-800">
          このアプリについて
        </h2>

        <p className="mb-4 text-sm leading-relaxed text-stone-600">
          描いた形を地図の道路上で再現するGPSアートのルートを、最適化アルゴリズムで探索します。
        </p>

        <div className="mb-4 flex flex-col gap-2 text-xs text-stone-500">
          <p className="font-medium text-stone-600">データの帰属</p>
          <p>
            道路データ:{' '}
            <a
              href="https://www.openstreetmap.org/copyright"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-stone-700"
            >
              © OpenStreetMap contributors
            </a>{' '}
            (
            <a
              href="https://opendatacommons.org/licenses/odbl/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-stone-700"
            >
              ODbL
            </a>
            )、{' '}
            <a
              href="https://overpass-api.de/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-stone-700"
            >
              Overpass API
            </a>{' '}
            経由
          </p>
          <p>
            地図タイル:{' '}
            <a
              href="https://www.openstreetmap.org/copyright"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-stone-700"
            >
              © OpenStreetMap contributors
            </a>
            、{' '}
            <a
              href="https://carto.com/attributions"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-stone-700"
            >
              © CARTO
            </a>
          </p>
        </div>

        <button
          type="button"
          onClick={onClose}
          className="w-full rounded-xl border border-stone-200 bg-stone-50 py-2 text-sm text-stone-700 hover:bg-stone-100"
        >
          閉じる
        </button>
      </div>
    </ModalShell>
  )
}
