"""
本番アプリ向けの探索速度プリセット定義。

デバッグ UI のデフォルト（defaults.py）とは独立して管理する。
プリセットごとに budget_s / restart_count / max_iterations / fetch_radius_m を変える。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SpeedPreset = Literal["fast", "normal", "thorough"]


@dataclass(frozen=True)
class SpeedPresetConfig:
    budget_s: float
    restart_count: int
    max_iterations: int
    fetch_radius_m: float


SPEED_PRESETS: dict[str, SpeedPresetConfig] = {
    "fast": SpeedPresetConfig(
        budget_s=10.0,
        restart_count=2,
        max_iterations=150,
        fetch_radius_m=3500.0,
    ),
    "normal": SpeedPresetConfig(
        budget_s=20.0,
        restart_count=5,
        max_iterations=300,
        fetch_radius_m=5000.0,
    ),
    "thorough": SpeedPresetConfig(
        budget_s=30.0,
        restart_count=10,
        max_iterations=500,
        fetch_radius_m=7000.0,
    ),
}

# 本番デフォルト: 回転自由（デバッグと逆）
PRODUCTION_IGNORE_SOURCE_ROTATION: bool = True

# Overpass 応答 way 件数の上限（安全弁。本番では fetch_radius_m で範囲を制御するため通常は到達しない）
PRODUCTION_OVERPASS_MAX_WAYS: int = 200_000

# 密度適応半径の定数
PILOT_QUERY_RADIUS_M: int = 300          # パイロットクエリの bbox 半径 (m)
PILOT_FALLBACK_DENSITY: float = 100.0    # パイロット失敗時のフォールバック密度 (ways/km²)
MAX_WAY_BUDGET_ADAPTIVE: int = 8_000     # 密度から半径を決める際の way 数予算
ADAPTIVE_RADIUS_MIN_M: float = 1_000.0   # 適応半径の最小値 (m)
