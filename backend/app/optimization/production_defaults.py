"""
本番アプリ向けの探索速度プリセット定義。

デバッグ UI のデフォルト（defaults.py）とは独立して管理する。
プリセットごとに budget_s / restart_count / max_iterations を変える。
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


SPEED_PRESETS: dict[str, SpeedPresetConfig] = {
    "fast": SpeedPresetConfig(
        budget_s=10.0,
        restart_count=2,
        max_iterations=150,
    ),
    "normal": SpeedPresetConfig(
        budget_s=20.0,
        restart_count=5,
        max_iterations=300,
    ),
    "thorough": SpeedPresetConfig(
        budget_s=30.0,
        restart_count=10,
        max_iterations=500,
    ),
}

# 本番デフォルト: 回転自由（デバッグと逆）
PRODUCTION_IGNORE_SOURCE_ROTATION: bool = True

DEFAULT_SPEED_PRESET: SpeedPreset = "fast"

# ユーザー指定の道路取得半径 (m)
FETCH_RADIUS_MIN_M: float = 1_000.0
FETCH_RADIUS_MAX_M: float = 5_000.0
DEFAULT_FETCH_RADIUS_M: float = 3_000.0

# Overpass 応答 way 件数の上限（安全弁）
PRODUCTION_OVERPASS_MAX_WAYS: int = 200_000

FETCH_AREA_TOO_LARGE_MESSAGE = (
    "探索範囲が大きすぎるか、道路が密すぎる可能性があります。"
    "探索範囲を小さくして再試行してください。"
)
