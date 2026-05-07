import type { Point } from '../lib/simplify'

type SketchPreviewProps = {
  points: Point[]
  className?: string
}

/** 点列を境界ボックス内に等比で収めて SVG で表示する */
export function SketchPreview({ points, className = '' }: SketchPreviewProps) {
  if (points.length < 2) return null

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }

  const vb = 100
  const pad = 8
  const bw = Math.max(maxX - minX, 1e-6)
  const bh = Math.max(maxY - minY, 1e-6)
  const scale = Math.min((vb - 2 * pad) / bw, (vb - 2 * pad) / bh)

  const left = (vb - bw * scale) / 2
  const top = (vb - bh * scale) / 2

  const toSvg = (p: Point) => `${left + (p.x - minX) * scale},${top + (p.y - minY) * scale}`

  const d = points.map(toSvg).join(' ')

  return (
    <div
      className={`overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-inner ${className}`}
      role="img"
      aria-label="簡略化された線のプレビュー"
    >
      <svg
        viewBox={`0 0 ${vb} ${vb}`}
        className="aspect-square h-auto w-full text-[#2d4a5e]"
        preserveAspectRatio="xMidYMid meet"
      >
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth={3}
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={d}
        />
      </svg>
    </div>
  )
}
