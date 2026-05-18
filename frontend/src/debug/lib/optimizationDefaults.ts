/**
 * 既定は backend/app/optimization/defaults.py と同値に保つこと。
 * （デバッグ UI の初期 state と API のデフォルトを揃える）
 */
export const DEFAULT_OPTIMIZATION_BUDGET_SECONDS = 10
export const DEFAULT_ANNEAL_SEED = 0
export const DEFAULT_MAX_ITERATIONS = 250
export const DEFAULT_RESTART_COUNT = 1
export const DEFAULT_IGNORE_SOURCE_ROTATION = false
export const DEFAULT_INITIAL_TEMPERATURE = 0.05
export const DEFAULT_FINAL_TEMPERATURE = 0.001
export const DEFAULT_TRANSLATION_STEP_M_RATIO = 0.08
export const DEFAULT_ROTATION_STEP_RAD = 0.35
export const DEFAULT_LOG_SCALE_STEP = 0.12
export const DEFAULT_TRACE_STRIDE = 5
