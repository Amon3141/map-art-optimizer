"""
最適化（グリッド探索）の既定値（時間予算・シード・再起動・鏡映・粗前処理・θ/スケール分割など）。

フロントの `frontend/src/debug/lib/optimizationDefaults.ts` の `DEFAULT_*` 定数と、
バックエンドの `AnnealOptions` の既定フィールドと同一に保つこと。
"""

DEFAULT_OPTIMIZATION_BUDGET_SECONDS: float = 10.0
DEFAULT_ANNEAL_SEED: int = 0
DEFAULT_NUM_RESTARTS: int = 1
DEFAULT_INCLUDE_MIRROR_STROKE: bool = False
DEFAULT_COARSE_PRESOLVE: bool = True
DEFAULT_COARSE_THETA_BINS: int = 3
DEFAULT_COARSE_SCALE_BINS: int = 3
DEFAULT_EVALUATION_MODE: str = "faithful"
