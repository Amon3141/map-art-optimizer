"""
最適化（焼きなまし）の既定値（時間予算・シード・温度・遷移幅など）。

フロントの `frontend/src/debug/lib/optimizationDefaults.ts` の `DEFAULT_*` 定数と、
バックエンドの `AnnealOptions` の既定フィールドと同一に保つこと。
"""

DEFAULT_OPTIMIZATION_BUDGET_SECONDS: float = 10.0
DEFAULT_ANNEAL_SEED: int = 0
DEFAULT_EVALUATION_MODE: str = "faithful"
DEFAULT_MAX_ITERATIONS: int = 250
DEFAULT_INITIAL_TEMPERATURE: float = 0.05
DEFAULT_FINAL_TEMPERATURE: float = 0.001
DEFAULT_TRANSLATION_STEP_M_RATIO: float = 0.08
DEFAULT_ROTATION_STEP_RAD: float = 0.35
DEFAULT_LOG_SCALE_STEP: float = 0.12
DEFAULT_TRACE_STRIDE: int = 5
