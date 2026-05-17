"""最適化パイプラインの固定パラメータと、複数モジュールで共有する定数。"""

# ルート構築・スコア正規化で共通（シンプルに一本化）
ROUTE_ARC_SAMPLES: int = 16

# スコア重みの既定（OptimizeWeights / API body と同値）
WEIGHT_SOURCE_ROTATION: float = 0.15
WEIGHT_SOURCE_SCALE: float = 0.02
WEIGHT_SOURCE_MIRROR: float = 0.0
WEIGHT_SHAPE_DISTANCE: float = 1.0
WEIGHT_ROUTE_LENGTH: float = 0.0
WEIGHT_EDGE_COUNT: float = 0.0
WEIGHT_TURN: float = 0.0
WEIGHT_UNREACHABLE: float = 1e6

# グリッド探索: 並進を bbox に対する小数比で試す (fx, fy)
GRID_TXY_FRACS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (0.12, 0.0),
    (-0.12, 0.0),
)

# グリッドで試す等方スケールの区間（θ は defaults.DEFAULT_COARSE_THETA_BINS で [0,2π) を等分）
COARSE_SCALE_MIN: float = 0.75
COARSE_SCALE_MAX: float = 1.35

# グリッド上の等方スケールのクリップ域
GRID_TRANSFORM_SCALE_MIN: float = 0.15
GRID_TRANSFORM_SCALE_MAX: float = 8.0
