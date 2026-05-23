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

# 本番 /api/optimize の既定: 回転自由（デバッグ UI 既定とは別）
IGNORE_SOURCE_ROTATION_DEFAULT: bool = True

DEFAULT_SPEED_PRESET: SpeedPreset = "fast"

FETCH_RADIUS_MIN_M: float = 1_000.0
FETCH_RADIUS_MAX_M: float = 5_000.0
DEFAULT_FETCH_RADIUS_M: float = 3_000.0

OVERPASS_MAX_WAYS: int = 250_000
