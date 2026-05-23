"""
本番アプリ向けの探索速度プリセットと取得範囲の既定値。

デバッグ UI のデフォルト（defaults.py）とは独立して管理する。
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


SPEED_PRESETS: dict[SpeedPreset, SpeedPresetConfig] = {
    "fast": SpeedPresetConfig(
        budget_s=5.0,
        restart_count=2,
        max_iterations=300,
    ),
    "normal": SpeedPresetConfig(
        budget_s=10.0,
        restart_count=3,
        max_iterations=400,
    ),
    "thorough": SpeedPresetConfig(
        budget_s=20.0,
        restart_count=5,
        max_iterations=550,
    ),
}

# 本番 /api/optimize の既定: 向き固定 ON（デバッグ UI 既定とは別）
IGNORE_SOURCE_ROTATION_DEFAULT: bool = False

DEFAULT_SPEED_PRESET: SpeedPreset = "fast"

FETCH_RADIUS_MIN_M: float = 1_000.0
FETCH_RADIUS_MAX_M: float = 5_000.0
DEFAULT_FETCH_RADIUS_M: float = 2_000.0

# 本番 /api/optimize: build_native_graph 直前のノード数上限（前処理前）
MAX_NATIVE_GRAPH_NODES: int = 35_000
