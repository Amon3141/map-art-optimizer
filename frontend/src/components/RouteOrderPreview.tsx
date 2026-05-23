import type { Point } from '../lib/simplify'

type Props = {
  paths: Point[][]
  className?: string
}

const VB = 100
const PAD = 8
const ARROW_LEN = 3.2
const ARROW_HALF = 1.3
const MARKER_R = 2.2
const MIN_SEG_FOR_ARROW = ARROW_LEN * 2.5
const LONGI_OFFSET = 1.5

const PATH_COLORS = ['#2d4a5e', '#5e2d4a', '#2d5e4a', '#4a5e2d', '#4a2d5e']

const pk = (x: number, y: number) => `${Math.round(x * 100)},${Math.round(y * 100)}`

/** 処理済みパス（複数コンポーネント対応）の巡回順を可視化する SVG プレビュー */
export function RouteOrderPreview({ paths, className = '' }: Props) {
  const validPaths = paths.filter((p) => p.length >= 2)
  if (validPaths.length === 0) return null

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const path of validPaths) {
    for (const p of path) {
      if (p.x < minX) minX = p.x
      if (p.y < minY) minY = p.y
      if (p.x > maxX) maxX = p.x
      if (p.y > maxY) maxY = p.y
    }
  }
  const bw = Math.max(maxX - minX, 1e-6)
  const bh = Math.max(maxY - minY, 1e-6)
  const scale = Math.min((VB - 2 * PAD) / bw, (VB - 2 * PAD) / bh)
  const left = (VB - bw * scale) / 2
  const top = (VB - bh * scale) / 2
  const sx = (p: Point) => left + (p.x - minX) * scale
  const sy = (p: Point) => top + (p.y - minY) * scale

  const isSingleCircuit = (() => {
    if (validPaths.length !== 1) return false
    const ks = validPaths[0].map((p) => pk(sx(p), sy(p)))
    return ks[0] === ks[ks.length - 1]
  })()

  const componentElements: React.ReactNode[] = validPaths.map((path, pathIdx) => {
    const color = PATH_COLORS[pathIdx % PATH_COLORS.length]
    const pathKeys = path.map((p) => pk(sx(p), sy(p)))
    const svgCoords = new Map<string, { x: number; y: number }>()
    const keyCounts = new Map<string, number>()
    for (let i = 0; i < path.length; i++) {
      const k = pathKeys[i]
      keyCounts.set(k, (keyCounts.get(k) ?? 0) + 1)
      if (!svgCoords.has(k)) svgCoords.set(k, { x: sx(path[i]), y: sy(path[i]) })
    }

    const startKey = pathKeys[0]
    const endKey = pathKeys[pathKeys.length - 1]
    const isCircuit = startKey === endKey

    const junctionKeys = new Set<string>()
    for (const [k, count] of keyCounts) {
      if (count > 1) junctionKeys.add(k)
    }
    const endpointKeys = new Set<string>()
    for (let i = 1; i < path.length - 1; i++) {
      if (pathKeys[i - 1] === pathKeys[i + 1]) endpointKeys.add(pathKeys[i])
    }

    const visitOrder = new Map<string, number[]>()
    let counter = 1
    for (let i = 0; i < pathKeys.length; i++) {
      const k = pathKeys[i]
      if (i === 0 || i === path.length - 1 || endpointKeys.has(k) || junctionKeys.has(k)) {
        const nums = visitOrder.get(k)
        if (nums) nums.push(counter++)
        else visitOrder.set(k, [counter++])
      }
    }

    const segDir = new Map<string, { fwd: number; bwd: number }>()
    for (let i = 0; i < path.length - 1; i++) {
      const x1 = sx(path[i]), y1 = sy(path[i])
      const x2 = sx(path[i + 1]), y2 = sy(path[i + 1])
      const isFwd = x1 < x2 || (x1 === x2 && y1 <= y2)
      const segKey = isFwd
        ? `${pk(x1, y1)}-${pk(x2, y2)}`
        : `${pk(x2, y2)}-${pk(x1, y1)}`
      const e = segDir.get(segKey) ?? { fwd: 0, bwd: 0 }
      if (isFwd) { e.fwd++ } else { e.bwd++ }
      segDir.set(segKey, e)
    }

    const arrows: React.ReactNode[] = []
    for (let i = 0; i < path.length - 1; i++) {
      const x1 = sx(path[i]), y1 = sy(path[i])
      const x2 = sx(path[i + 1]), y2 = sy(path[i + 1])
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.hypot(dx, dy)
      if (len < MIN_SEG_FOR_ARROW) continue

      const ux = dx / len, uy = dy / len
      const isFwd = x1 < x2 || (x1 === x2 && y1 <= y2)
      const segKey = isFwd
        ? `${pk(x1, y1)}-${pk(x2, y2)}`
        : `${pk(x2, y2)}-${pk(x1, y1)}`
      const entry = segDir.get(segKey)!
      const bidir = entry.fwd > 0 && entry.bwd > 0
      const maxOffset = Math.max(0, len / 2 - ARROW_LEN - 0.5)
      const longi = bidir ? Math.min(LONGI_OFFSET, maxOffset) : 0

      const mx = (x1 + x2) / 2 + ux * longi
      const my = (y1 + y2) / 2 + uy * longi
      const tx = mx + ux * ARROW_LEN
      const ty = my + uy * ARROW_LEN
      const b1x = mx - uy * ARROW_HALF
      const b1y = my + ux * ARROW_HALF
      const b2x = mx + uy * ARROW_HALF
      const b2y = my - ux * ARROW_HALF

      arrows.push(
        <polygon
          key={i}
          points={`${tx},${ty} ${b1x},${b1y} ${b2x},${b2y}`}
          fill={color}
          opacity={0.55}
        />,
      )
    }

    const labels: React.ReactNode[] = []
    for (const [key, nums] of visitOrder) {
      const coord = svgCoords.get(key)!
      const isStart = key === startKey
      const isEnd = key === endKey
      const labelColor = isStart ? '#059669' : isEnd ? '#d97706' : '#9ca3af'
      labels.push(
        <text
          key={key}
          x={coord.x + 2}
          y={coord.y - 1.5}
          fontSize={3.5}
          fill={labelColor}
          fontFamily="sans-serif"
        >
          {nums.join(',')}
        </text>,
      )
    }

    const startCoord = svgCoords.get(startKey)!
    const endCoord = svgCoords.get(endKey)!
    const polylinePoints = path.map((p) => `${sx(p)},${sy(p)}`).join(' ')

    return (
      <g key={pathIdx}>
        <polyline
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={polylinePoints}
        />
        {arrows}
        {labels}
        {!isCircuit && (
          <circle
            cx={endCoord.x}
            cy={endCoord.y}
            r={MARKER_R}
            fill="#d97706"
            stroke="white"
            strokeWidth={0.8}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {isCircuit ? (
          <>
            <circle
              cx={startCoord.x}
              cy={startCoord.y}
              r={MARKER_R + 1.2}
              fill="none"
              stroke="#059669"
              strokeWidth={0.8}
              vectorEffect="non-scaling-stroke"
            />
            <circle cx={startCoord.x} cy={startCoord.y} r={MARKER_R} fill="#059669" />
          </>
        ) : (
          <circle
            cx={startCoord.x}
            cy={startCoord.y}
            r={MARKER_R}
            fill="#059669"
            stroke="white"
            strokeWidth={0.8}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </g>
    )
  })

  return (
    <div
      className={`relative min-h-0 min-w-0 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-inner ${className}`}
      role="img"
      aria-label="巡回順プレビュー"
    >
      <svg
        viewBox={`0 0 ${VB} ${VB}`}
        className="block h-full w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {componentElements}
      </svg>

      <div
        className="pointer-events-none absolute bottom-1.5 right-2.5 flex items-center gap-2 text-[10px] text-stone-400"
        aria-hidden
      >
        {isSingleCircuit ? (
          <span className="flex items-center gap-1">
            <span className="size-2 shrink-0 rounded-full bg-emerald-600" />
            始/終
          </span>
        ) : (
          <>
            <span className="flex items-center gap-1">
              <span className="size-2 shrink-0 rounded-full bg-emerald-600" />
              始点
            </span>
            <span className="flex items-center gap-1">
              <span className="size-2 shrink-0 rounded-full bg-amber-600" />
              終点
            </span>
          </>
        )}
      </div>
    </div>
  )
}
