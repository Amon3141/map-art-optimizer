import type { Point } from '../lib/simplify'

type SketchPreviewProps = {
  strokes: Point[][]
  /** SVG プレビューの線幅（px）。最適化パスデータには影響しない */
  strokeWidth?: number
  className?: string
}

/** 複数ストロークをコンテナいっぱいに等比で収めて SVG で表示する */
export function SketchPreview({
  strokes,
  strokeWidth = 2,
  className = '',
}: SketchPreviewProps) {
  const totalPoints = strokes.reduce((s, stroke) => s + stroke.length, 0)
  if (strokes.length === 0 || totalPoints < 2) return null

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const stroke of strokes) {
    for (const p of stroke) {
      minX = Math.min(minX, p.x)
      minY = Math.min(minY, p.y)
      maxX = Math.max(maxX, p.x)
      maxY = Math.max(maxY, p.y)
    }
  }

  const vb = 100
  const pad = 8
  const bw = Math.max(maxX - minX, 1e-6)
  const bh = Math.max(maxY - minY, 1e-6)
  const scale = Math.min((vb - 2 * pad) / bw, (vb - 2 * pad) / bh)
  const left = (vb - bw * scale) / 2
  const top = (vb - bh * scale) / 2

  const toSvg = (p: Point) =>
    `${left + (p.x - minX) * scale},${top + (p.y - minY) * scale}`

  return (
    <div
      className={`overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-inner ${className}`}
      role="img"
      aria-label="ストロークプレビュー"
    >
      <svg
        viewBox={`0 0 ${vb} ${vb}`}
        className="h-full w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {strokes.map((stroke, i) => {
          if (stroke.length < 2) return null
          return (
            <polyline
              key={i}
              fill="none"
              stroke="#2d4a5e"
              strokeWidth={strokeWidth}
              vectorEffect="non-scaling-stroke"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={stroke.map(toSvg).join(' ')}
            />
          )
        })}
      </svg>
    </div>
  )
}
