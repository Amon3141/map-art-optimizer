from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    WEIGHT_DIJKSTRA_FALLBACK,
    WEIGHT_LOCAL_OFFSET,
    WEIGHT_OUT_OF_GRAPH,
    WEIGHT_SHAPE_DISTANCE,
    WEIGHT_SOURCE_ROTATION,
    WEIGHT_SOURCE_SCALE,
    WEIGHT_TURN,
    WEIGHT_UNREACHABLE,
)
from .defaults import (
    DEFAULT_ANNEAL_SEED,
    DEFAULT_FINAL_TEMPERATURE,
    DEFAULT_IGNORE_OPTIMIZATION_BUDGET,
    DEFAULT_IGNORE_SOURCE_ROTATION,
    DEFAULT_INITIAL_TEMPERATURE,
    DEFAULT_LOG_SCALE_STEP,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_N_LOCAL_TRIALS,
    DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
    DEFAULT_RESTART_COUNT,
    DEFAULT_ROTATION_STEP_RAD,
    DEFAULT_TRACE_STRIDE,
    DEFAULT_TRANSLATION_STEP_M_RATIO,
)


@dataclass
class StrokePoint:
    x: float
    y: float


@dataclass
class Transform:
    """平面変換（メートル）。基準形をグラフ bbox 中心周りに回転・等方スケールし、平行移動。"""

    tx_m: float = 0.0
    ty_m: float = 0.0
    theta_rad: float = 0.0
    scale: float = 1.0


@dataclass
class OptimizeWeights:
    """無次元スコア（正規化項）向けの既定重み。"""

    source_rotation: float = WEIGHT_SOURCE_ROTATION
    source_scale: float = WEIGHT_SOURCE_SCALE
    shape_distance: float = WEIGHT_SHAPE_DISTANCE
    turn: float = WEIGHT_TURN
    unreachable: float = WEIGHT_UNREACHABLE
    out_of_graph: float = WEIGHT_OUT_OF_GRAPH
    dijkstra_fallback: float = WEIGHT_DIJKSTRA_FALLBACK
    local_offset: float = WEIGHT_LOCAL_OFFSET


@dataclass
class AnnealOptions:
    """デバッグ API / UI から渡す探索パラメータ（マルチスタート焼きなまし）。"""

    optimization_budget_seconds: float = DEFAULT_OPTIMIZATION_BUDGET_SECONDS
    seed: int = DEFAULT_ANNEAL_SEED
    # 各試行（初期解）ごとにこの回数まで。試行数で割り振らない。
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    restart_count: int = DEFAULT_RESTART_COUNT
    ignore_optimization_budget: bool = DEFAULT_IGNORE_OPTIMIZATION_BUDGET
    ignore_source_rotation: bool = DEFAULT_IGNORE_SOURCE_ROTATION
    initial_temperature: float = DEFAULT_INITIAL_TEMPERATURE
    final_temperature: float = DEFAULT_FINAL_TEMPERATURE
    translation_step_m_ratio: float = DEFAULT_TRANSLATION_STEP_M_RATIO
    rotation_step_rad: float = DEFAULT_ROTATION_STEP_RAD
    log_scale_step: float = DEFAULT_LOG_SCALE_STEP
    trace_stride: int = DEFAULT_TRACE_STRIDE
    # ジョイント SA: global perturbation ごとに試す local offset サンプル数（1=従来と等価）
    n_local_trials: int = DEFAULT_N_LOCAL_TRIALS


@dataclass
class ScoreBreakdown:
    """無次元スコア内訳。shape_distance は双方向チャンファー。"""

    source_rotation: float
    source_scale: float
    shape_distance: float
    turn: float
    unreachable: float
    out_of_graph: float = 0.0
    dijkstra_fallback: float = 0.0

    def total(self, w: OptimizeWeights) -> float:
        return (
            w.source_rotation * self.source_rotation
            + w.source_scale * self.source_scale
            + w.shape_distance * self.shape_distance
            + w.turn * self.turn
            + w.unreachable * self.unreachable
            + w.out_of_graph * self.out_of_graph
            + w.dijkstra_fallback * self.dijkstra_fallback
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "source_rotation": self.source_rotation,
            "source_scale": self.source_scale,
            "shape_distance": self.shape_distance,
            "turn": self.turn,
            "unreachable": self.unreachable,
            "out_of_graph": self.out_of_graph,
            "dijkstra_fallback": self.dijkstra_fallback,
        }


@dataclass
class RouteBuildResult:
    edge_ids: list[str]
    """連結ルートの折れ線（メートル、順序付き）。"""
    polyline_xy_m: list[tuple[float, float]]
    reachable: bool
    """全サンプル間の最短経路が存在したか。"""
    dijkstra_failures: int = 0


@dataclass
class TraceStep:
    step_index: int
    temperature: float
    accepted: bool
    score_total: float
    score_terms: dict[str, float]
    transform: dict[str, Any]
    edge_ids: list[str]
    # マルチコンポーネント時に全コンポーネントの edge_ids を格納（シングルは空リスト）
    edge_ids_per_component: list[list[str]] = field(default_factory=list)


@dataclass
class AnnealRunResult:
    transform: Transform
    route: RouteBuildResult
    breakdown: ScoreBreakdown
    score: float
    trace_steps: list[TraceStep]
    iterations_planned: int
    iterations_completed: int
    accepted_moves: int
    deadline_hit: bool

    @property
    def acceptance_rate(self) -> float:
        if self.iterations_completed <= 0:
            return 0.0
        return self.accepted_moves / float(self.iterations_completed)


@dataclass
class RestartResult:
    restart_index: int
    seed: int
    initial_transform: Transform
    best_transform: Transform
    best_edge_ids: list[str]
    best_polyline_xy_m: list[tuple[float, float]]
    best_score: float
    best_breakdown: ScoreBreakdown
    best_route_length_m: float
    iterations_planned: int
    iterations_completed: int
    accepted_moves: int
    acceptance_rate: float
    deadline_hit: bool
    trace_steps: list[TraceStep] = field(default_factory=list)


@dataclass
class OptimizeResult:
    best_transform: Transform
    best_edge_ids: list[str]
    best_polyline_xy_m: list[tuple[float, float]]
    best_score: float
    best_breakdown: ScoreBreakdown
    best_restart_index: int
    """ベストルートのグラフ上幾何長（メートル）。到達不能時は 0 に近い値の可能性あり。"""
    best_route_length_m: float = 0.0
    restart_results: list[RestartResult] = field(default_factory=list)
    candidates_geojson: dict[str, Any] = field(default_factory=dict)
    optimizer_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentOptimizeResult:
    """ジョイント最適化における1コンポーネントの結果。"""

    component_index: int
    best_edge_ids: list[str]
    best_polyline_xy_m: list[tuple[float, float]]
    best_score: float
    best_breakdown: ScoreBreakdown
    route_length_m: float


@dataclass
class JointOptimizeResult:
    """マルチコンポーネントのジョイント焼きなまし結果。"""

    components: list[ComponentOptimizeResult]
    best_joint_score: float
    best_transform: Transform
    best_local_offsets: list[tuple[float, float]]
    candidates_geojson: dict[str, Any]
    restart_results: list[RestartResult] = field(default_factory=list)
    optimizer_meta: dict[str, Any] = field(default_factory=dict)
