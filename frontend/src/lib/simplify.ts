export type Point = { x: number; y: number }

/** Ramer–Douglas–Peucker in pixel space. 大きいほど点が減る（形は粗くなる）。docs/architecture.md 参照 */
export const SIMPLIFY_TOLERANCE_PX = 5

function perpendicularDistance(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (dx === 0 && dy === 0) {
    return Math.hypot(p.x - a.x, p.y - a.y)
  }
  const t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)
  const tClamped = Math.max(0, Math.min(1, t))
  const proj = { x: a.x + tClamped * dx, y: a.y + tClamped * dy }
  return Math.hypot(p.x - proj.x, p.y - proj.y)
}

function douglasPeucker(points: Point[], epsilon: number): Point[] {
  if (points.length <= 2) return [...points]
  let maxDist = 0
  let index = 0
  const end = points.length - 1
  for (let i = 1; i < end; i++) {
    const d = perpendicularDistance(points[i], points[0], points[end])
    if (d > maxDist) {
      index = i
      maxDist = d
    }
  }
  if (maxDist > epsilon) {
    const left = douglasPeucker(points.slice(0, index + 1), epsilon)
    const right = douglasPeucker(points.slice(index), epsilon)
    return [...left.slice(0, -1), ...right]
  }
  return [points[0], points[end]]
}

export function simplifyStroke(points: Point[], epsilon = SIMPLIFY_TOLERANCE_PX): Point[] {
  if (points.length < 2) return [...points]
  return douglasPeucker(points, epsilon)
}
