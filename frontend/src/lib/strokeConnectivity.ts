import type { Point } from './simplify'

export const GEOMETRY_EPS = 1e-10

/**
 * 2線分 [a1,a2] と [b1,b2] の交差パラメータを返す。
 * 平行 or 非交差なら null。t は線分A、u は線分B 上のパラメータ（0..1）。
 * 端点交差も含む（eps を考慮）。
 */
export function segmentIntersectionParam(
  a1: Point,
  a2: Point,
  b1: Point,
  b2: Point,
): { t: number; u: number } | null {
  const dx1 = a2.x - a1.x
  const dy1 = a2.y - a1.y
  const dx2 = b2.x - b1.x
  const dy2 = b2.y - b1.y

  const denom = dx1 * dy2 - dy1 * dx2
  if (Math.abs(denom) < GEOMETRY_EPS) return null

  const t = ((b1.x - a1.x) * dy2 - (b1.y - a1.y) * dx2) / denom
  const u = ((b1.x - a1.x) * dy1 - (b1.y - a1.y) * dx1) / denom

  if (t < -GEOMETRY_EPS || t > 1 + GEOMETRY_EPS || u < -GEOMETRY_EPS || u > 1 + GEOMETRY_EPS)
    return null
  return { t, u }
}

/** 2線分 [a1,a2] と [b1,b2] が交差または接しているか（端点含む） */
function segmentsIntersect(a1: Point, a2: Point, b1: Point, b2: Point): boolean {
  if (segmentIntersectionParam(a1, a2, b1, b2) !== null) return true
  // 平行・重なりの場合は端点チェック
  return (
    pointOnSegment(a1, b1, b2) ||
    pointOnSegment(a2, b1, b2) ||
    pointOnSegment(b1, a1, a2) ||
    pointOnSegment(b2, a1, a2)
  )
}

function pointOnSegment(p: Point, a: Point, b: Point): boolean {
  const eps = GEOMETRY_EPS
  const minX = Math.min(a.x, b.x) - eps
  const maxX = Math.max(a.x, b.x) + eps
  const minY = Math.min(a.y, b.y) - eps
  const maxY = Math.max(a.y, b.y) + eps
  if (p.x < minX || p.x > maxX || p.y < minY || p.y > maxY) return false
  const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
  return Math.abs(cross) < eps * Math.max(1, Math.abs(b.x - a.x), Math.abs(b.y - a.y))
}

/** ストローク i と j のいずれかのエッジペアが交差しているか */
function strokesTouching(s1: Point[], s2: Point[]): boolean {
  for (let i = 0; i < s1.length - 1; i++) {
    for (let j = 0; j < s2.length - 1; j++) {
      if (segmentsIntersect(s1[i], s1[i + 1], s2[j], s2[j + 1])) return true
    }
  }
  return false
}

/**
 * ストロークの connected components を返す。
 * 戻り値: 各 component の ストロークインデックス配列の配列
 * 例: [[0, 2], [1]] → ストローク 0,2 が接続、1 は孤立
 */
export function findConnectedComponents(strokes: Point[][]): number[][] {
  const n = strokes.length
  const parent = Array.from({ length: n }, (_, i) => i)

  function find(x: number): number {
    while (parent[x] !== x) {
      parent[x] = parent[parent[x]]
      x = parent[x]
    }
    return x
  }

  function union(x: number, y: number) {
    const px = find(x)
    const py = find(y)
    if (px !== py) parent[px] = py
  }

  for (let i = 0; i < n; i++) {
    if (strokes[i].length < 2) continue
    for (let j = i + 1; j < n; j++) {
      if (strokes[j].length < 2) continue
      if (strokesTouching(strokes[i], strokes[j])) {
        union(i, j)
      }
    }
  }

  const groups = new Map<number, number[]>()
  for (let i = 0; i < n; i++) {
    const root = find(i)
    const g = groups.get(root)
    if (g) g.push(i)
    else groups.set(root, [i])
  }

  return Array.from(groups.values())
}

/** 孤立しているストロークのインデックス集合を返す（自分以外の全ストロークと接触していない） */
export function isolatedStrokeIndices(strokes: Point[][]): Set<number> {
  if (strokes.length <= 1) return new Set()
  const components = findConnectedComponents(strokes)
  if (components.length === 1) return new Set()

  // 最大 component 以外のストロークを孤立扱いにする
  const largest = components.reduce((a, b) => (a.length >= b.length ? a : b))
  const mainSet = new Set(largest)
  const isolated = new Set<number>()
  for (let i = 0; i < strokes.length; i++) {
    if (!mainSet.has(i)) isolated.add(i)
  }
  return isolated
}

/** 全ストロークが1つの connected component に属しているか */
export function isFullyConnected(strokes: Point[][]): boolean {
  if (strokes.length <= 1) return true
  const components = findConnectedComponents(strokes)
  return components.length === 1
}
