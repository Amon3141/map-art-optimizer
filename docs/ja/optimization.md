# 最適化

マルチスタート焼きなましが変換パラメータを探索し、各ステップで入力折れ線を道路グラフへスナップする。

実装: `backend/app/optimization/`

## 本番 API

`POST /api/optimize`（`backend/app/routes.py`）

### リクエスト

```json
{
  "stroke_components": [[{"x": 0.1, "y": 0.3}, ...], ...],
  "center_lon": 139.76,
  "center_lat": 35.68,
  "speed_preset": "normal",
  "fetch_radius_m": 2000,
  "ignore_source_rotation": false
}
```

| フィールド | 既定 | 説明 |
|-----------|------|------|
| `speed_preset` | `"normal"` | `fast` \| `normal` \| `thorough` |
| `fetch_radius_m` | 2000 | 道路取得半径（m） |
| `ignore_source_rotation` | `false` | `false` のときスケッチの向きからの回転にペナルティ |

速度プリセット（`backend/app/optimization/app_defaults.py`）:

| プリセット | 予算 (s) | restart | 最大反復 |
|-----------|---------|---------|---------|
| fast | 5 | 2 | 300 |
| normal | 10 | 3 | 400 |
| thorough | 20 | 5 | 550 |

### レスポンス（概要）

```json
{
  "candidates_geojson": { "type": "FeatureCollection", ... },
  "ranked_candidates": [{ "candidate_id": "...", "rank": 1, "score_total": 0.12, ... }],
  "best_score": 0.123,
  "route_length_km": 4.2,
  "restarts": [{ "trace_steps": [...], ... }],
  "components": [{ "component_index": 0, "best_score": ..., ... }]
}
```

- 本番では `record_trace` は常に有効
- クライアント側トレース再生用に `edges_geojson` を含む

ルーティング（`backend/app/optimization/pipeline.py`）:

- 1 コンポーネント → `run_simulated_annealing`
- 2 コンポーネント以上 → `run_joint_simulated_annealing`

## 変換モデル

キャンバスストロークをメートル空間の base polyline に変換（`backend/app/optimization/transform.py`）:

- 単一: `stroke_to_base_polyline_m`
- 複数: `strokes_to_base_polylines_m_shared` — 全体 bbox から共通スケールを算出

適用:

```
apply_transform(base_polyline, Transform(theta, scale, tx, ty), graph_center)
```

## スナップ

`backend/app/optimization/snap_route.py`:

1. 変換後折れ線セグメントを近傍グラフ辺へ射影（空間索引）
2. セグメントごとに射影順の候補ノード DAG を構築
3. 角度ズレ・横方向ズレ・長さをコストとする smooth DP
4. DP 失敗時はスナップ点間を Dijkstra で接続
5. セグメントルートを edge ID 列に連結

焼きなましの各 iteration でスナップが走るため、空間索引と探索帯による候補絞り込みが性能上重要。

## スコア

重み付き和を最小化（`backend/app/optimization/scoring.py`、重みは `backend/app/optimization/constants.py`）:

| 項 | 意味 |
|----|------|
| `shape_distance` | スナップ元とルートの双方向 Chamfer 型距離 |
| `source_rotation` | スケッチの向きからの回転ペナルティ（45° までは 0、150° で正規化） |
| `source_scale` | `abs(log(scale))` |
| `out_of_graph` | 変換後折れ線がグラフ bbox 外に出た割合 |
| `dijkstra_fallback` | Dijkstra フォールバックが必要だったセグメントの割合 |
| `unreachable` | ルート構築失敗時の大ペナルティ |
| `local_offset` | ジョイント SA のみ: コンポーネント offset ノルム合計 ÷ グラフ対角 |

既定重み（`OptimizeWeights`）: `shape_distance=1.0`, `source_rotation=0.38`, `source_scale=0.02`, `unreachable=1e6`, `out_of_graph=2.0`, `dijkstra_fallback=0.3`, `local_offset=0.5`.

## 焼きなまし

コア: `backend/app/optimization/anneal.py`、オーケストレーション: `backend/app/optimization/run.py`

### シングルコンポーネント状態

```
{ tx_m, ty_m, theta_rad, scale }
```

- 提案: translate / rotate / scale（または compound）からランダム選択、Gaussian ノイズ、ステップ幅は温度比に連動
- 採択: 改善は必ず採択、悪化は `exp(-Δ / T)` で幾何冷却
- Basin hopping: 温度比 > 0.5 で 5% の確率でランダムジャンプ
- 停滞脱出: best 停滞時にランダムジャンプ、採択温度を一時 reheat

### ジョイント状態（マルチコンポーネント）

```
global_t: { tx_m, ty_m, theta_rad, scale }
local_offsets: [{ dx_m, dy_m }, ...]
```

- global 変換はシングル SA と同様に提案
- 各 global 提案に対し `n_local_trials`（既定 4）回 local offset をサンプルし、最良スコアで採択判定
- コンポーネントスコアは弧長加重平均 + local offset ペナルティ

### 初期解

restart 前に `_coarse_grid_search` が予算の ~15% を 4×4 位置 × 3 角度 × 3 スケールのグリッド（最大 144 評価）に使う。多様性を保ち `restart_count` 個の初期変換を選ぶ。

## 候補選択

`backend/app/optimization/candidate_select.py` が全 restart の trace からスコア margin でフィルタ、transform 空間で dedup し、最大 5 件の `ranked_candidates` を返す。

## トレース形式

各 restart の `trace_steps` に含む: `temperature`, `accepted`, `score_total`, `score_terms`, `transform`, `edge_ids`、（ジョイント）`edge_ids_per_component`.

フロント再生: `frontend/src/lib/routeOverlay.ts` — `overlayForCandidate`, `rebuildRouteForTraceStep`.

共有 UI: `AnnealingTraceSlider`, `RouteInfoPanel`（`frontend/src/components/`）。

## モジュール一覧

| ファイル | 役割 |
|---------|------|
| `constants.py` | スコア重み、弧長サンプル数、スケールクリップ |
| `defaults.py` | デバッグ用 `AnnealOptions` 既定 |
| `app_defaults.py` | 本番速度プリセット、取得半径、ノード上限 |
| `types.py` | `Transform`, `TraceStep`, `OptimizeResult`, `JointOptimizeResult` |
| `transform.py` | ストローク → base polyline, `apply_transform` |
| `snap_route.py` | スナップ + ルート構築 |
| `scoring.py` | ルート評価 |
| `anneal.py` | シングル・ジョイント SA（1 restart 分） |
| `run.py` | マルチスタート、GeoJSON 出力 |
| `serialize.py` | レスポンスシリアライズ |
| `pipeline.py` | 最適化パイプライン全体 |

## 関連ドキュメント

- [入力前処理](input-preprocessing.md)
- [道路グラフ](road-graph.md)
- [開発](development.md) — 全パラメータを調整できるデバッグ API
