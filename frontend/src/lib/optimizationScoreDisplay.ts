/** 生スコア (小さいほど良い) → 0–100 点表示。区分的線形。 */
const ANCHORS: readonly { raw: number; points: number }[] = [
  { raw: 0.00, points: 100 },
  { raw: 0.03, points: 95 },
  { raw: 0.04, points: 85 },
  { raw: 0.05, points: 70 },
  { raw: 0.10, points: 0 },
]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

/** 最適化の生スコアを 0–100 のマッチ度に変換する。 */
export function optimizationScoreToDisplayPoints(rawScore: number): number {
  const s = Math.max(0, rawScore)
  if (s >= ANCHORS[ANCHORS.length - 1].raw) {
    return 0
  }
  for (let i = 0; i < ANCHORS.length - 1; i++) {
    const lo = ANCHORS[i]
    const hi = ANCHORS[i + 1]
    if (s <= hi.raw) {
      const t = hi.raw === lo.raw ? 0 : (s - lo.raw) / (hi.raw - lo.raw)
      return Math.round(lerp(lo.points, hi.points, t))
    }
  }
  return 0
}

/**
 * マッチ度の段階色（高→低: 緑 → 青 → オレンジ → 赤）。
 * RouteOrderPreview の始点/終点色・Sidebar の #4a6f8a / CTA の #b14f33 など既存トーンに合わせる。
 */
export function optimizationScoreDisplayColorClass(displayPoints: number): string {
  if (displayPoints >= 90) return 'text-[#2d7a5e]'
  if (displayPoints >= 80) return 'text-[#4a6f8a]'
  if (displayPoints >= 65) return 'text-[#d97706]'
  return 'text-[#b14f33]'
}

// 検証: 0→100, 0.03→95, 0.04→85, 0.05→70, 0.10→0
