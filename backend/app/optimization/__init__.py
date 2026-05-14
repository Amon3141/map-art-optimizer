"""道路グラフ上のルート探索・スコアリング（本番パイプライン用）。デバッグ API から呼び出す。"""

from .run import run_simulated_annealing

__all__ = ["run_simulated_annealing"]