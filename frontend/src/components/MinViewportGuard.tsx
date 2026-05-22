import { VIEWPORT_GUARD_Z_INDEX } from '../lib/modalLayers'

export function MinViewportGuard() {
  return (
    <div
      className={[
        'fixed inset-0 hidden h-full w-full flex-col items-center justify-center bg-[#faf8f4] px-6 text-center',
        'max-[319px]:flex',
      ].join(' ')}
      style={{ zIndex: VIEWPORT_GUARD_Z_INDEX }}
      role="alert"
      aria-live="polite"
    >
      <div className="flex max-w-xs flex-col gap-1 text-center text-sm font-medium text-stone-600">
        <p>画面幅が狭すぎます。</p>
        <p>画面を広げてください。</p>
      </div>
    </div>
  )
}
