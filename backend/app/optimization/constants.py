"""最適化パイプラインの固定パラメータと、複数モジュールで共有する定数。"""

# ルート構築・スコア正規化で共通（シンプルに一本化）
ROUTE_ARC_SAMPLES: int = 16

# スコア重みの既定（OptimizeWeights / API body と同値）
WEIGHT_SOURCE_ROTATION: float = 0.38
WEIGHT_SOURCE_SCALE: float = 0.02
WEIGHT_SHAPE_DISTANCE: float = 1.0
WEIGHT_TURN: float = 0.0
WEIGHT_UNREACHABLE: float = 1e6
# グラフ bbox 外への逸脱ペナルティ。形がグラフ端に押し込まれた状態を罰し、SA の勾配を作る。
WEIGHT_OUT_OF_GRAPH: float = 2.0
# smooth DP 失敗 → Dijkstra フォールバック率のペナルティ。形状不整合の補助指標。
WEIGHT_DIJKSTRA_FALLBACK: float = 0.3
# マルチコンポーネント時のローカルオフセットペナルティ（|offset| / graph_diagonal を正規化済み）。
WEIGHT_LOCAL_OFFSET: float = 0.5

# 順序対応 shape loss と coverage loss の合成比
SHAPE_COVERAGE_WEIGHT: float = 0.35

# スナップ元の回転角ペナルティ。30 度までは無罰、超過分をこの度幅で割って正規化（小さいほど角度制約が強い）。
SOURCE_ROTATION_FREE_DEG: float = 30.0
SOURCE_ROTATION_NORMALIZATION_DEG: float = 150.0

# 焼きなまし中の等方スケールのクリップ域
TRANSFORM_SCALE_MIN: float = 0.15
TRANSFORM_SCALE_MAX: float = 8.0

# ジョイント SA: global perturbation ごとに試す local offset サンプル数
N_LOCAL_TRIALS_PER_GLOBAL: int = 4
