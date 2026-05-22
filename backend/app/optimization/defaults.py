"""
最適化（焼きなまし）の既定値（時間予算・シード・温度・遷移幅など）。

フロントの `frontend/src/debug/lib/optimizationDefaults.ts` の `DEFAULT_*` 定数と、
バックエンドの `AnnealOptions` の既定フィールドと同一に保つこと。
"""

DEFAULT_OPTIMIZATION_BUDGET_SECONDS: float = 10.0
DEFAULT_ANNEAL_SEED: int = 0
DEFAULT_MAX_ITERATIONS: int = 250
DEFAULT_RESTART_COUNT: int = 1
DEFAULT_IGNORE_OPTIMIZATION_BUDGET: bool = False
DEFAULT_IGNORE_SOURCE_ROTATION: bool = False
DEFAULT_INITIAL_TEMPERATURE: float = 0.05
DEFAULT_FINAL_TEMPERATURE: float = 0.001
DEFAULT_TRANSLATION_STEP_M_RATIO: float = 0.08
DEFAULT_ROTATION_STEP_RAD: float = 0.35
DEFAULT_LOG_SCALE_STEP: float = 0.12
DEFAULT_TRACE_STRIDE: int = 5
# 冷え込み時の遷移幅フロア（temp_ratio に比例、これ未満にはならない）
DEFAULT_STEP_SCALE_MIN: float = 0.03
DEFAULT_N_LOCAL_TRIALS: int = 4

# トレース横断の表示候補選択（件数は可変。include 帯内かつ transform が離れたもののみ）
DEFAULT_MAX_DISPLAY_CANDIDATES: int = 5
DEFAULT_SCORE_INCLUDE_MARGIN: float = 0.015
DEFAULT_CANDIDATE_DIVERSITY_MIN: float = 0.12
