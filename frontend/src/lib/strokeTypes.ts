import type { Point } from './simplify'

export type { Point }

export type InputMode = 'freehand' | 'pen' | 'text'
export type StrokeMode = 'single_path' | 'free_draw'

/** 最適化向けの全ストローク合計点数の上限（全入力モード共通） */
export const MAX_STROKE_POINTS = 150

export type StrokeData = {
  inputMode: InputMode
  /** テキスト入力時は常に 'free_draw' */
  strokeMode: StrokeMode
  /** 各ストロークを描画順に保持した点配列の配列 */
  strokes: Point[][]
}
