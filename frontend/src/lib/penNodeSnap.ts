import type { Point } from './simplify'

/** Pen-mode vertex snap radius in CSS pixels (same coords as canvas getBoundingClientRect). */
export const PEN_SNAP_RADIUS_PX = 14

function isSamePoint(a: Point, b: Point): boolean {
  return a.x === b.x && a.y === b.y
}

function isExcluded(p: Point, exclude: Point[]): boolean {
  return exclude.some((e) => isSamePoint(p, e))
}

/** Last 1–2 vertices of the in-progress stroke (avoids retracing the current edge). */
export function recentPenPointsToExclude(penCurrentPts: Point[]): Point[] {
  const n = penCurrentPts.length
  const out: Point[] = []
  if (n >= 1) out.push(penCurrentPts[n - 1]!)
  if (n >= 2) out.push(penCurrentPts[n - 2]!)
  return out
}

export function collectPenSnapNodes(
  strokes: Point[][],
  penCurrentPts: Point[],
  /** Nodes at these positions are not snap targets. */
  exclude: Point[] = [],
): Point[] {
  const nodes: Point[] = []
  for (const stroke of strokes) {
    for (const p of stroke) {
      if (isExcluded(p, exclude)) continue
      nodes.push(p)
    }
  }
  for (const p of penCurrentPts) {
    if (isExcluded(p, exclude)) continue
    nodes.push(p)
  }
  return nodes
}

export function findNearestSnapNode(
  cursor: Point,
  nodes: Point[],
  radiusPx: number,
): { node: Point; dist: number } | null {
  const radiusSq = radiusPx * radiusPx
  let best: { node: Point; dist: number } | null = null
  for (const node of nodes) {
    const distSq = (cursor.x - node.x) ** 2 + (cursor.y - node.y) ** 2
    if (distSq > radiusSq) continue
    const dist = Math.sqrt(distSq)
    if (!best || dist < best.dist) best = { node, dist }
  }
  return best
}

export function applyPenSnap(
  raw: Point,
  strokes: Point[][],
  penCurrentPts: Point[],
): { point: Point; snapTarget: Point | null } {
  const nodes = collectPenSnapNodes(strokes, penCurrentPts, recentPenPointsToExclude(penCurrentPts))
  const hit = findNearestSnapNode(raw, nodes, PEN_SNAP_RADIUS_PX)
  if (!hit) return { point: raw, snapTarget: null }
  return { point: { x: hit.node.x, y: hit.node.y }, snapTarget: hit.node }
}
