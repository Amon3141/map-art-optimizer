"""最適化パイプラインの固定パラメータと、複数モジュールで共有する定数。"""

# ルート構築・スコア正規化で共通（シンプルに一本化）
ROUTE_ARC_SAMPLES: int = 16

# スコア重みの既定（OptimizeWeights / API body と同値）
WEIGHT_SOURCE_ROTATION: float = 0.15
WEIGHT_SOURCE_SCALE: float = 0.02
WEIGHT_SHAPE_DISTANCE: float = 1.0
WEIGHT_ROUTE_LENGTH: float = 0.0
WEIGHT_EDGE_COUNT: float = 0.0
WEIGHT_TURN: float = 0.0
WEIGHT_UNREACHABLE: float = 1e6

# 順序対応 shape loss と coverage loss の合成比
SHAPE_COVERAGE_WEIGHT: float = 0.35

# elegant mode の簡潔さ項は shape が十分良い時だけ強く効かせる
ELEGANCE_GATE_THRESHOLD: float = 0.08

# 焼きなまし中の等方スケールのクリップ域
TRANSFORM_SCALE_MIN: float = 0.15
TRANSFORM_SCALE_MAX: float = 8.0
