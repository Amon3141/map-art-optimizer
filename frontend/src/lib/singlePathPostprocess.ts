import type { Point } from './simplify'
import { GEOMETRY_EPS, segmentIntersectionParam } from './strokeConnectivity'

// ピクセル座標系での同一点判定閾値（GEOMETRY_EPS は線形代数用なので別途設定）
const POINT_MERGE_EPS = 1e-6

interface Graph {
  vertices: Point[]
  adj: Array<Array<{ to: number; edgeIdx: number }>>
  edges: Array<{ u: number; v: number; weight: number }>
}

interface AugEdge {
  u: number
  v: number
  weight: number
  used: boolean
}

interface AugGraph {
  vertices: Point[]
  adj: Array<Array<{ to: number; edgeIdx: number }>>
  edges: AugEdge[]
}

// ---------------------------------------------------------------------------
// グラフ構築
// ---------------------------------------------------------------------------

function gridKey(x: number, y: number, cellSize: number): string {
  return `${Math.floor(x / cellSize)},${Math.floor(y / cellSize)}`
}

function mergePoint(
  pt: Point,
  vertices: Point[],
  bucket: Map<string, number[]>,
  cellSize: number,
): number {
  const cx = Math.floor(pt.x / cellSize)
  const cy = Math.floor(pt.y / cellSize)
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const key = `${cx + dx},${cy + dy}`
      const ids = bucket.get(key)
      if (!ids) continue
      for (const id of ids) {
        const v = vertices[id]
        if (Math.abs(v.x - pt.x) < POINT_MERGE_EPS && Math.abs(v.y - pt.y) < POINT_MERGE_EPS)
          return id
      }
    }
  }
  const id = vertices.length
  vertices.push({ x: pt.x, y: pt.y })
  const key = gridKey(pt.x, pt.y, cellSize)
  const arr = bucket.get(key)
  if (arr) arr.push(id)
  else bucket.set(key, [id])
  return id
}

function buildGraph(strokes: Point[][]): Graph {
  // 全セグメントを列挙
  type Seg = { p0: Point; p1: Point; strokeIdx: number; segIdx: number }
  const segs: Seg[] = []
  for (let si = 0; si < strokes.length; si++) {
    const s = strokes[si]
    for (let pi = 0; pi < s.length - 1; pi++) {
      segs.push({ p0: s[pi], p1: s[pi + 1], strokeIdx: si, segIdx: pi })
    }
  }

  // 各セグメントのsplit点 (t parameter) を収集
  const splits: Map<number, number[]> = new Map()
  for (let i = 0; i < segs.length; i++) splits.set(i, [])

  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const a = segs[i]
      const b = segs[j]
      // 同一ストローク内の隣接セグメントはスキップ（端点を共有するだけで自明）
      if (a.strokeIdx === b.strokeIdx && Math.abs(a.segIdx - b.segIdx) === 1) continue

      const res = segmentIntersectionParam(a.p0, a.p1, b.p0, b.p1)
      if (res === null) {
        // 平行ケース: 端点一致のみ（頂点統合で処理）
        continue
      }
      const { t, u } = res
      // 内点交差のみ split 対象（端点付近は頂点統合に任せる）
      if (t > GEOMETRY_EPS && t < 1 - GEOMETRY_EPS) splits.get(i)!.push(t)
      if (u > GEOMETRY_EPS && u < 1 - GEOMETRY_EPS) splits.get(j)!.push(u)
    }
  }

  const cellSize = Math.max(POINT_MERGE_EPS * 10, 1e-5)
  const vertices: Point[] = []
  const bucket = new Map<string, number[]>()
  const adj: Array<Array<{ to: number; edgeIdx: number }>> = []
  const edges: Array<{ u: number; v: number; weight: number }> = []

  function addVertex(p: Point): number {
    const id = mergePoint(p, vertices, bucket, cellSize)
    while (adj.length <= id) adj.push([])
    return id
  }

  function addEdge(uid: number, vid: number) {
    if (uid === vid) return // 長さゼロのエッジは無視
    const u = vertices[uid]
    const v = vertices[vid]
    const w = Math.hypot(v.x - u.x, v.y - u.y)
    if (w < POINT_MERGE_EPS) return
    const eidx = edges.length
    edges.push({ u: uid, v: vid, weight: w })
    adj[uid].push({ to: vid, edgeIdx: eidx })
    adj[vid].push({ to: uid, edgeIdx: eidx })
  }

  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i]
    const ts = splits.get(i)!
    ts.sort((a, b) => a - b)

    // 重複除去
    const uniqueTs: number[] = []
    for (const t of ts) {
      if (uniqueTs.length === 0 || t - uniqueTs[uniqueTs.length - 1] > GEOMETRY_EPS) {
        uniqueTs.push(t)
      }
    }

    // 端点と split 点を順に頂点化してエッジを追加
    const pts: Point[] = [seg.p0]
    for (const t of uniqueTs) {
      pts.push({
        x: seg.p0.x + t * (seg.p1.x - seg.p0.x),
        y: seg.p0.y + t * (seg.p1.y - seg.p0.y),
      })
    }
    pts.push(seg.p1)

    let prevId = addVertex(pts[0])
    for (let k = 1; k < pts.length; k++) {
      const curId = addVertex(pts[k])
      addEdge(prevId, curId)
      prevId = curId
    }
  }

  return { vertices, adj, edges }
}

// ---------------------------------------------------------------------------
// 奇数次頂点の検出
// ---------------------------------------------------------------------------

function findOddDegreeVertices(g: Graph): number[] {
  const degree = new Array<number>(g.vertices.length).fill(0)
  for (const e of g.edges) {
    degree[e.u]++
    degree[e.v]++
  }
  const odd: number[] = []
  for (let i = 0; i < degree.length; i++) {
    if (degree[i] % 2 === 1) odd.push(i)
  }
  return odd
}

// ---------------------------------------------------------------------------
// Dijkstra
// ---------------------------------------------------------------------------

function dijkstra(
  g: Graph,
  src: number,
): { dist: number[]; prev: (number | null)[] } {
  const n = g.vertices.length
  const dist = new Array<number>(n).fill(Infinity)
  const prev = new Array<number | null>(n).fill(null)
  dist[src] = 0

  // 簡易優先度キュー（小規模グラフ向け）
  const queue: [number, number][] = [[0, src]] // [cost, vertex]

  while (queue.length > 0) {
    // 最小要素を線形スキャンで取得（N<=300 程度なので十分）
    let minIdx = 0
    for (let i = 1; i < queue.length; i++) {
      if (queue[i][0] < queue[minIdx][0]) minIdx = i
    }
    const [d, v] = queue[minIdx]
    queue.splice(minIdx, 1)
    if (d > dist[v]) continue

    for (const { to, edgeIdx } of g.adj[v]) {
      const w = g.edges[edgeIdx].weight
      if (dist[v] + w < dist[to]) {
        dist[to] = dist[v] + w
        prev[to] = v
        queue.push([dist[to], to])
      }
    }
  }

  return { dist, prev }
}

function reconstructPath(prev: (number | null)[], src: number, dst: number): number[] {
  const path: number[] = []
  let cur: number | null = dst
  while (cur !== null && cur !== src) {
    path.push(cur)
    cur = prev[cur]
  }
  path.push(src)
  path.reverse()
  return path
}

function shortestPathsBetweenOdd(
  g: Graph,
  oddVerts: number[],
): { dist: number[][]; paths: number[][] } {
  const k = oddVerts.length
  const dist: number[][] = Array.from({ length: k }, () => new Array<number>(k).fill(0))
  const paths: number[][] = Array.from({ length: k * k }, () => [])

  for (let i = 0; i < k; i++) {
    const { dist: d, prev } = dijkstra(g, oddVerts[i])
    for (let j = 0; j < k; j++) {
      dist[i][j] = d[oddVerts[j]]
      paths[i * k + j] = reconstructPath(prev, oddVerts[i], oddVerts[j])
    }
  }

  return { dist, paths }
}

// ---------------------------------------------------------------------------
// 最小重みマッチング
// ---------------------------------------------------------------------------

function matchingBitmaskDP(dist: number[][]): [number, number][] {
  const k = dist.length
  const size = 1 << k
  const dp = new Array<number>(size).fill(Infinity)
  const parent = new Array<number>(size).fill(-1)
  dp[0] = 0

  for (let mask = 1; mask < size; mask++) {
    // 最下位 set bit
    let first = -1
    for (let i = 0; i < k; i++) {
      if (mask & (1 << i)) {
        first = i
        break
      }
    }
    for (let j = first + 1; j < k; j++) {
      if (!(mask & (1 << j))) continue
      const sub = mask ^ (1 << first) ^ (1 << j)
      const cost = dp[sub] + dist[first][j]
      if (cost < dp[mask]) {
        dp[mask] = cost
        parent[mask] = j
      }
    }
  }

  // マッチングペアを復元
  const pairs: [number, number][] = []
  let mask = size - 1
  while (mask > 0) {
    let first = -1
    for (let i = 0; i < k; i++) {
      if (mask & (1 << i)) {
        first = i
        break
      }
    }
    const j = parent[mask]
    pairs.push([first, j])
    mask ^= (1 << first) | (1 << j)
  }
  return pairs
}

function matchingGreedy(k: number, dist: number[][]): [number, number][] {
  // (cost, i, j) のリストを作成してソート
  const candidates: [number, number, number][] = []
  for (let i = 0; i < k; i++) {
    for (let j = i + 1; j < k; j++) {
      candidates.push([dist[i][j], i, j])
    }
  }
  candidates.sort((a, b) => a[0] - b[0])

  const used = new Array<boolean>(k).fill(false)
  const pairs: [number, number][] = []
  for (const [, i, j] of candidates) {
    if (!used[i] && !used[j]) {
      pairs.push([i, j])
      used[i] = true
      used[j] = true
    }
  }
  return pairs
}

function minWeightPerfectMatching(dist: number[][]): [number, number][] {
  const k = dist.length
  if (k === 0) return []
  return k <= 20 ? matchingBitmaskDP(dist) : matchingGreedy(k, dist)
}

function matchingCost(pairs: [number, number][], dist: number[][]): number {
  return pairs.reduce((s, [i, j]) => s + dist[i][j], 0)
}

// ---------------------------------------------------------------------------
// Euler モード選択（PATH vs CIRCUIT）
// ---------------------------------------------------------------------------

type EulerChoice =
  | { mode: 'circuit'; start: number; matching: [number, number][] }
  | { mode: 'path'; start: number; end: number; matching: [number, number][] }

function chooseEulerMode(
  oddVerts: number[],
  dist: number[][],
): EulerChoice {
  const k = oddVerts.length

  if (k === 0) {
    return { mode: 'circuit', start: 0, matching: [] }
  }

  if (k === 2) {
    return { mode: 'path', start: oddVerts[0], end: oddVerts[1], matching: [] }
  }

  // Circuit: 全 k 頂点をマッチング
  const circuitMatching = minWeightPerfectMatching(dist)
  const circuitCost = matchingCost(circuitMatching, dist)

  // Path: C(k,2) 通りの (始点,終点) 選択で残り k-2 をマッチング
  let bestPathCost = Infinity
  let bestPathPairs: [number, number][] = []
  let bestStart = 0
  let bestEnd = 1

  for (let si = 0; si < k; si++) {
    for (let ei = si + 1; ei < k; ei++) {
      // si, ei を除いた残り k-2 頂点のインデックス
      const remaining: number[] = []
      for (let x = 0; x < k; x++) {
        if (x !== si && x !== ei) remaining.push(x)
      }
      if (remaining.length === 0) {
        // k==2 のケースは上で処理済みだが念のため
        if (bestPathCost > 0) {
          bestPathCost = 0
          bestPathPairs = []
          bestStart = si
          bestEnd = ei
        }
        continue
      }

      const subDist = remaining.map((r) => remaining.map((c) => dist[r][c]))
      const subPairs = minWeightPerfectMatching(subDist)
      // subPairs のインデックスは remaining[] へのインデックスなので元に戻す
      const remapped: [number, number][] = subPairs.map(([a, b]) => [remaining[a], remaining[b]])
      const cost = matchingCost(remapped, dist)
      if (cost < bestPathCost) {
        bestPathCost = cost
        bestPathPairs = remapped
        bestStart = si
        bestEnd = ei
      }
    }
  }

  if (bestPathCost <= circuitCost) {
    return {
      mode: 'path',
      start: oddVerts[bestStart],
      end: oddVerts[bestEnd],
      matching: bestPathPairs,
    }
  } else {
    return { mode: 'circuit', start: oddVerts[0], matching: circuitMatching }
  }
}

// ---------------------------------------------------------------------------
// 拡張グラフ構築（マッチングパスを重複エッジとして追加）
// ---------------------------------------------------------------------------

function buildAugmentedGraph(
  g: Graph,
  oddVerts: number[],
  matching: [number, number][],
  paths: number[][],
): AugGraph {
  const k = oddVerts.length
  const augEdges: AugEdge[] = g.edges.map((e) => ({ ...e, used: false }))
  const augAdj: Array<Array<{ to: number; edgeIdx: number }>> = g.adj.map((list) =>
    list.map((e) => ({ ...e })),
  )

  while (augAdj.length < g.vertices.length) augAdj.push([])

  for (const [pi, pj] of matching) {
    const path = paths[pi * k + pj]
    // path 上の各エッジを重複エッジとして追加
    for (let i = 0; i < path.length - 1; i++) {
      const u = path[i]
      const v = path[i + 1]
      const w = Math.hypot(
        g.vertices[v].x - g.vertices[u].x,
        g.vertices[v].y - g.vertices[u].y,
      )
      const eidx = augEdges.length
      augEdges.push({ u, v, weight: w, used: false })
      while (augAdj.length <= Math.max(u, v)) augAdj.push([])
      augAdj[u].push({ to: v, edgeIdx: eidx })
      augAdj[v].push({ to: u, edgeIdx: eidx })
    }
  }

  return { vertices: g.vertices, adj: augAdj, edges: augEdges }
}

// ---------------------------------------------------------------------------
// Hierholzer でオイラー路/回路を抽出
// ---------------------------------------------------------------------------

function hierholzer(mg: AugGraph, start: number): number[] {
  const ptr = new Array<number>(mg.vertices.length).fill(0)
  const stack: number[] = [start]
  const circuit: number[] = []

  while (stack.length > 0) {
    const v = stack[stack.length - 1]
    const adj = mg.adj[v]
    // ptr[v] を進めて未使用エッジを探す
    while (ptr[v] < adj.length && mg.edges[adj[ptr[v]].edgeIdx].used) {
      ptr[v]++
    }
    if (ptr[v] < adj.length) {
      const { to, edgeIdx } = adj[ptr[v]]
      mg.edges[edgeIdx].used = true
      ptr[v]++
      stack.push(to)
    } else {
      circuit.push(stack.pop()!)
    }
  }

  return circuit.reverse()
}

// ---------------------------------------------------------------------------
// エントリポイント
// ---------------------------------------------------------------------------

/**
 * single_path モード用後処理。
 * 空間的に connected な複数ストロークを Chinese Postman で一本の順序付き頂点リストに変換する。
 * 全エッジを最小コストで辿る（一部エッジを往復する場合あり）。
 */
export function buildSinglePath(strokes: Point[][]): Point[] {
  // 空入力
  const validStrokes = strokes.filter((s) => s.length >= 2)
  if (validStrokes.length === 0) {
    return strokes.length > 0 && strokes[0].length >= 1 ? [strokes[0][0]] : []
  }

  // 1本のストローク → 自己交差チェックなしで早期リターン
  if (validStrokes.length === 1) {
    // 単純に交差があるかだけ確認（自己交差なしなら即返す）
    const s = validStrokes[0]
    let hasSelfIntersect = false
    outer: for (let i = 0; i < s.length - 1; i++) {
      for (let j = i + 2; j < s.length - 1; j++) {
        const res = segmentIntersectionParam(s[i], s[i + 1], s[j], s[j + 1])
        if (res !== null && res.t > GEOMETRY_EPS && res.t < 1 - GEOMETRY_EPS) {
          hasSelfIntersect = true
          break outer
        }
      }
    }
    if (!hasSelfIntersect) return s
  }

  // グラフ構築
  const g = buildGraph(validStrokes)

  if (g.vertices.length === 0 || g.edges.length === 0) {
    return validStrokes[0]
  }

  // 奇数次頂点を検出
  const oddVerts = findOddDegreeVertices(g)

  // 奇数次頂点が 0 の場合: Euler circuit（追加なし）
  if (oddVerts.length === 0) {
    const aug: AugGraph = {
      vertices: g.vertices,
      adj: g.adj.map((list) => list.map((e) => ({ ...e }))),
      edges: g.edges.map((e) => ({ ...e, used: false })),
    }
    const circuit = hierholzer(aug, 0)
    return circuit.map((id) => g.vertices[id])
  }

  // 奇数次頂点が 2 の場合: Euler path（追加なし）
  if (oddVerts.length === 2) {
    const aug: AugGraph = {
      vertices: g.vertices,
      adj: g.adj.map((list) => list.map((e) => ({ ...e }))),
      edges: g.edges.map((e) => ({ ...e, used: false })),
    }
    const path = hierholzer(aug, oddVerts[0])
    return path.map((id) => g.vertices[id])
  }

  // 一般ケース: マッチングで奇数次頂点を削減
  const { dist, paths } = shortestPathsBetweenOdd(g, oddVerts)
  const choice = chooseEulerMode(oddVerts, dist)

  const aug = buildAugmentedGraph(g, oddVerts, choice.matching, paths)
  const startVertex = choice.start
  const vertexIds = hierholzer(aug, startVertex)
  return vertexIds.map((id) => g.vertices[id])
}
