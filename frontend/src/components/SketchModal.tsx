import { useEffect, useRef, useState } from 'react'
import { MdOutlineDraw } from 'react-icons/md'
import { type Point, simplifyStroke } from '../lib/simplify_old'

export type SketchModalProps = {
  onClose: () => void
  onConfirm: (points: Point[]) => void
}

function drawStroke(
  ctx: CanvasRenderingContext2D,
  points: Point[],
  width: number,
  height: number,
) {
  ctx.clearRect(0, 0, width, height)
  if (points.length < 2) return
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#2d4a5e'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(points[0].x, points[0].y)
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y)
  }
  ctx.stroke()
}

export function SketchModal({ onClose, onConfirm }: SketchModalProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [points, setPoints] = useState<Point[]>([])
  const [drawing, setDrawing] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = Math.max(1, Math.floor(rect.width * dpr))
    canvas.height = Math.max(1, Math.floor(rect.height * dpr))
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    drawStroke(ctx, points, rect.width, rect.height)
  }, [points])

  const clientToPoint = (ev: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const r = canvas.getBoundingClientRect()
    return { x: ev.clientX - r.left, y: ev.clientY - r.top }
  }

  const onPointerDown = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    ev.currentTarget.setPointerCapture(ev.pointerId)
    setDrawing(true)
    setHint(null)
    const p = clientToPoint(ev)
    // 新しいストローク開始（既存の線は消して書き直し）
    setPoints([p])
  }

  const onPointerMove = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const p = clientToPoint(ev)
    setPoints((prev) => {
      const last = prev[prev.length - 1]
      if (last && Math.hypot(p.x - last.x, p.y - last.y) < 1.5) return prev
      return [...prev, p]
    })
  }

  const endStroke = () => {
    if (!drawing) return
    setDrawing(false)
    setPoints((prev) => {
      if (prev.length < 2) return prev
      return simplifyStroke(prev)
    })
  }

  const handleConfirm = () => {
    if (points.length < 2) {
      setHint('線を描いてから決定してください。')
      return
    }
    onConfirm(points)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/25 p-4 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sketch-title"
    >
      <div className="w-full max-w-lg rounded-2xl border border-stone-200/80 bg-[#fdfbf7] p-5 shadow-xl sm:max-w-2xl sm:p-6 md:max-w-3xl lg:max-w-4xl lg:p-8">
        <h2
          id="sketch-title"
          className="flex items-center gap-2 text-lg font-medium text-stone-800 lg:text-xl"
        >
          <MdOutlineDraw className="h-6 w-6 shrink-0 text-stone-700" aria-hidden />
          形を描く
        </h2>
        <p className="mt-1.5 text-sm text-stone-600">
          指またはマウスでなぞってください。もう一度キャンバスに触れると、いまの線を消して書き直せます。
        </p>
        <div className="relative mt-4">
          <canvas
            ref={canvasRef}
            className="h-64 w-full cursor-crosshair touch-none rounded-xl border border-dashed border-stone-300 bg-white sm:h-80 md:h-[22rem] lg:h-[26rem]"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endStroke}
            onPointerCancel={endStroke}
          />
          {points.length >= 2 ? (
            <p
              className="pointer-events-none absolute bottom-2 right-2 select-none text-[11px] text-stone-400"
              aria-live="polite"
            >
              {drawing ? `${points.length} 点（描画中）` : `${points.length} 点（簡略化後）`}
            </p>
          ) : null}
        </div>
        {hint ? <p className="mt-2 text-sm text-amber-800">{hint}</p> : null}
        <div className="mt-4 flex justify-end gap-2 lg:mt-6">
          <button
            type="button"
            className="rounded-lg border border-stone-300 bg-white px-4 py-2 text-sm text-stone-700 shadow-sm hover:bg-stone-50"
            onClick={onClose}
          >
            キャンセル
          </button>
          <button
            type="button"
            className="rounded-lg bg-[#4a6f8a] px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-[#3d5f77]"
            onClick={handleConfirm}
          >
            決定
          </button>
        </div>
      </div>
    </div>
  )
}
