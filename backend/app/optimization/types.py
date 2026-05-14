from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    WEIGHT_EDGE_COUNT,
    WEIGHT_LENGTH,
    WEIGHT_SHAPE,
    WEIGHT_TURN,
    WEIGHT_UNREACHABLE,
)
from .defaults import (
    DEFAULT_ANNEAL_SEED,
    DEFAULT_COARSE_PRESOLVE,
    DEFAULT_COARSE_SCALE_BINS,
    DEFAULT_COARSE_THETA_BINS,
    DEFAULT_INCLUDE_MIRROR_STROKE,
    DEFAULT_NUM_RESTARTS,
    DEFAULT_OPTIMIZATION_BUDGET_SECONDS,
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
    shape: float = WEIGHT_SHAPE
    length: float = WEIGHT_LENGTH
    edge_count: float = WEIGHT_EDGE_COUNT
    turn: float = WEIGHT_TURN
    unreachable: float = WEIGHT_UNREACHABLE


@dataclass
class AnnealOptions:
    """デバッグ API / UI から渡す探索パラメータ（離散グリッド探索）。"""

    optimization_budget_seconds: float = DEFAULT_OPTIMIZATION_BUDGET_SECONDS
    seed: int = DEFAULT_ANNEAL_SEED
    num_restarts: int = DEFAULT_NUM_RESTARTS
    include_mirror_stroke: bool = DEFAULT_INCLUDE_MIRROR_STROKE
    coarse_presolve: bool = DEFAULT_COARSE_PRESOLVE
    coarse_theta_bins: int = DEFAULT_COARSE_THETA_BINS
    coarse_scale_bins: int = DEFAULT_COARSE_SCALE_BINS


@dataclass
class ScoreBreakdown:
    """無次元スコア内訳。shape はターゲット→ルートのチャンファー。"""
    shape: float
    length: float
    edge_count: float
    turn: float
    unreachable: float

    def total(self, w: OptimizeWeights) -> float:
        return (
            w.shape * self.shape
            + w.length * self.length
            + w.edge_count * self.edge_count
            + w.turn * self.turn
            + w.unreachable * self.unreachable
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "shape": self.shape,
            "length": self.length,
            "edge_count": self.edge_count,
            "turn": self.turn,
            "unreachable": self.unreachable,
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
    transform: dict[str, float]
    edge_ids: list[str]


@dataclass
class OptimizeResult:
    best_transform: Transform
    best_edge_ids: list[str]
    best_polyline_xy_m: list[tuple[float, float]]
    best_score: float
    best_breakdown: ScoreBreakdown
    """ベストルートのグラフ上幾何長（メートル）。到達不能時は 0 に近い値の可能性あり。"""
    best_route_length_m: float = 0.0
    trace_steps: list[TraceStep] = field(default_factory=list)
    candidates_geojson: dict[str, Any] = field(default_factory=dict)
    optimizer_meta: dict[str, Any] = field(default_factory=dict)
