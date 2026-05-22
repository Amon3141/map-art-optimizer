// 最適化の設定の規定値 (backend/app/optimization/defaults.py と同値に保つこと。)
export const DEFAULT_OPTIMIZATION_BUDGET_SECONDS = 10
export const DEFAULT_ANNEAL_SEED = 0
export const DEFAULT_MAX_ITERATIONS = 250
export const DEFAULT_RESTART_COUNT = 1
export const DEFAULT_IGNORE_OPTIMIZATION_BUDGET = false
export const DEFAULT_IGNORE_SOURCE_ROTATION = false
export const DEFAULT_INITIAL_TEMPERATURE = 0.05
export const DEFAULT_FINAL_TEMPERATURE = 0.001
export const DEFAULT_TRANSLATION_STEP_M_RATIO = 0.08
export const DEFAULT_ROTATION_STEP_RAD = 0.35
export const DEFAULT_LOG_SCALE_STEP = 0.12
export const DEFAULT_TRACE_STRIDE = 5
export const DEFAULT_STEP_SCALE_MIN = 0.03

// 評価関数の重みの既定値（backend/app/optimization/constants.py と同値に保つこと）
export const DEFAULT_WEIGHT_SOURCE_ROTATION = 0.38
export const DEFAULT_WEIGHT_SOURCE_SCALE = 0.02
export const DEFAULT_WEIGHT_SHAPE_DISTANCE = 1.0
export const DEFAULT_WEIGHT_TURN = 0.0
export const DEFAULT_WEIGHT_UNREACHABLE = 1e6
export const DEFAULT_WEIGHT_OUT_OF_GRAPH = 2.0
export const DEFAULT_WEIGHT_DIJKSTRA_FALLBACK = 0.3
