"""
グラフ構築の数値既定値。

フロントの `frontend/src/debug/lib/graphPreview.ts` の `defaultGraphBuildOptions()`
と同一に保つこと（API 既定・テストの基準）。
"""

DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG = 10.0
DEFAULT_ROAD_MERGE_DISTANCE_M = 20.0
DEFAULT_ROAD_MERGE_ANGLE_DEG = 22.0
DEFAULT_ROAD_MERGE_MIN_OVERLAP_M = 100.0
DEFAULT_ROAD_MERGE_MIN_OVERLAP_RATIO = 0.25
DEFAULT_ROAD_MERGE_ANCHOR_DELTA_M = 2.0
# 0 = 実行時に max(2 * road_merge_distance_m, 50) を使う
DEFAULT_ROAD_MERGE_MAX_ANCHOR_OFFSET_M = 0.0
