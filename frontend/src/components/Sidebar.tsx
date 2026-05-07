import { MdOutlineDraw } from 'react-icons/md'
import { Link } from 'react-router-dom'
import { SketchPreview } from './SketchPreview'
import type { Point } from '../lib/simplify'

const showDebugNav = import.meta.env.VITE_DEBUG === 'true'

export type SidebarProps = {
  targetKm: number
  onTargetKmChange: (km: number) => void
  strokePoints: Point[] | null
  onOpenSketch: () => void
}

export function Sidebar({
  targetKm,
  onTargetKmChange,
  strokePoints,
  onOpenSketch,
}: SidebarProps) {
  const hasShape = Boolean(strokePoints && strokePoints.length >= 2)

  return (
    <aside className="flex w-full shrink-0 flex-col gap-4.5 p-5 pb-4 lg:max-w-sm lg:py-5 lg:pl-5 lg:pr-0">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">
          地図アート作成機
        </h1>
        <p className="text-sm leading-relaxed text-stone-600">
          キャンバスに描いた形を、地図の道路上で再現するルートを探します。
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1 rounded-xl border border-dashed border-stone-400 bg-white py-3 text-sm font-medium text-stone-800 shadow-sm hover:border-[#4a6f8a] hover:bg-[#f3f6f8]"
          onClick={onOpenSketch}
        >
          <MdOutlineDraw className="h-5 w-5 shrink-0 text-stone-700" aria-hidden />
          {hasShape ? '形を描き直す' : '形を描く'}
        </button>

        {hasShape && strokePoints ? (
          <SketchPreview
            points={strokePoints}
            className="mx-auto w-full max-w-[220px]"
          />
        ) : null}
      </div>

      <div className="flex flex-col gap-2.5">
        <label
          className="block text-sm font-medium text-stone-700"
        >
          距離の目安（km）
          <input
            type="number"
            min={1}
            step={1}
            value={Number.isFinite(targetKm) ? targetKm : 1}
            onChange={(e) => onTargetKmChange(Math.max(1, parseInt(e.target.value, 10) || 1))}
            className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-stone-900 shadow-inner outline-none ring-[#4a6f8a] focus:ring-2"
          />
        </label>
        <button
          type="button"
          className="rounded-xl bg-[#c45c3e] py-3 text-sm font-semibold text-white shadow-md hover:bg-[#b14f33]"
          onClick={() => {
            /* 将来: 最適化APIを呼ぶ */
          }}
        >
          地図アートを作成
        </button>
      </div>

      {showDebugNav ? (
        <Link
          to="/debug"
          className="mt-auto text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline"
        >
          デバッグページへ →
        </Link>
      ) : null}
    </aside>
  )
}
