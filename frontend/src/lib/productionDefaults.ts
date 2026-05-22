/** 本番アプリ向け速度プリセット定義。バックエンドの production_defaults.py と同期して保つ。 */

export type SpeedPreset = 'fast' | 'normal' | 'thorough'

export type SpeedPresetMeta = {
  label: string
  description: string
}

export const SPEED_PRESET_META: Record<SpeedPreset, SpeedPresetMeta> = {
  fast: { label: '速め', description: '約10秒' },
  normal: { label: 'ふつう', description: '約20秒' },
  thorough: { label: 'じっくり', description: '約30秒' },
}

export const DEFAULT_SPEED_PRESET: SpeedPreset = 'fast'

/** 本番デフォルト: 向き固定 OFF（回転自由） */
export const DEFAULT_IGNORE_SOURCE_ROTATION = true

/** プリセット別の estimated budget (秒) — UI のプログレス表示に使う */
export const PRESET_BUDGET_S: Record<SpeedPreset, number> = {
  fast: 10,
  normal: 20,
  thorough: 30,
}

/** 道路取得半径 (m) — バックエンドの production_defaults.py と同期して保つ */
export const FETCH_RADIUS_MIN_M = 1000
export const FETCH_RADIUS_MAX_M = 5000
export const DEFAULT_FETCH_RADIUS_M = 3000
export const FETCH_RADIUS_STEP_M = 500

export const FETCH_AREA_TOO_LARGE_CODE = 'fetch_area_too_large' as const
