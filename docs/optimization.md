# 最適化（設計メモ）

**現状:** デバッグ用にスナップ元のマルチスタート焼きなましが実装済み（`backend/app/optimization/`、`POST /api/debug/optimize`）。シングルコンポーネント（1本のパス）とマルチコンポーネント（複数の独立ストローク）の両方をサポートする。

---

## 1. この文書の位置づけ

| 書くこと | まだ書かないこと |
|---|---|
| 最適化アルゴリズムの要件・制約 | 本番向けの性能保証 |
| API スキーマ・スコア項の定義 | 評価関数の最終的な重み調整の結論 |
| セクション 8: 現行実装の詳細 | 本番 `/api` エンドポイントの詳細 |

---

## 2. プロダクト上の狙い（最適化に関わる部分）

- **入力**: キャンバス上の形（手書き・ペン・テキスト）。探索エリア内で**位置・回転・スケール**を調べ、道路ネット上で「絵」に近い一連のルートを探す。複数の独立したストロークコンポーネントも対応。
- **出力**: 候補ルートの GeoJSON（現状はベスト 1 本）。将来は複数候補のランキング提示を予定。
- **距離**: 目安として整数 km（±2 km 程度の許容は将来目標）。

詳細スコープは `docs/product.md` を参照。

---

## 3. 要件（機能）

### 3.1 インプット

- フロントで簡略化・前処理済みの点列（キャンバス正規化座標）。
- 1 つ以上の connected component（各 component は `buildSinglePath` 済みの点列）。component 数でシングル / ジョイント SA を切り替える。
- 探索エリア（bbox）と道路グラフ（Overpass 由来）。

詳しいフロント側の前処理（Chinese Postman、connected components）は [`input_shape.md`](./input_shape.md) を参照。

### 3.2 アウトプット（API）

- **正（canonical）**: GeoJSON `FeatureCollection`（WGS84）。
- **ジオメトリ**: 候補ごとに `LineString`、座標は `[経度, 緯度]`。
- **候補と Feature の対応**: ルート候補 1 本につき `Feature` を 1 つ。マルチコンポーネント時は全コンポーネントのルートを結合した `LineString` が返る。

### 3.3 `properties` の方針

スキーマの細目はアルゴリズム確定後に固める。含めたい情報: 幾何変換（回転角・スケール・並進）、評価スコア、ルート長（単位明示）。

---

## 4. 制約条件

### 4.1 道路ネットのみ

ルートは地図上で通行可能な線に沿う。データは OSM を Overpass で取得し FastAPI がプロキシ（`docs/architecture.md`）。

### 4.2 一筆書き

各コンポーネント内のルートは切れ目のない連続パスとする。フロントの `buildSinglePath`（Chinese Postman）で一筆書き化済みの点列を受け取る前提であり、バックエンドでの再構成は行わない。

### 4.3 距離

ユーザー指定の目標長さに対し、グラフ上の実長が許容範囲に入ること（閾値は未確定）。

---

## 5. 評価・目的関数まわりの懸念

### 5.1 「形が近い」と「走るのに適している」は別軸

- 目的関数は複数項に分ける（形状類似度・旋回ペナルティ・道路種別コスト等）。
- または段階的: まず候補を生成し、走行性でフィルタ／再ランキング。

### 5.2 完全一致より「人間の認識に近い柔軟さ」

- 形状類似度は粗いサンプリング・順序対応距離など、過度な一致を強制しない設計を検討。
- 認識（似ているか）と走行性を別レイヤで考え、後から重み付け。

---

## 6. メタヒューリスティック・探索の方向

- **焼きなまし法**: 状態 `(theta, scale, tx, ty)` を摂動し、スナップ後評価でベスト候補を探索。マルチスタート（ランダム初期解を複数試す）で多様性を確保。
- **マルチコンポーネント（ジョイント SA）**: グローバル変換 1 本と、コンポーネントごとのローカルオフセット `(dx, dy)` を joint に最適化。

---

## 7. 実装フェーズで試すアルゴリズムの方向性（メモ・未確定）

1. **離散探索（グリッド／サンプリング）** — 位置・角度・スケールを粗く総当たりし、スナップ後にスコア。
2. **道路グラフ上の形状マッチング（粗い版）** — Fréchet / DTW、点とグラフの距離の和等。
3. **貪欲スナップ＋ローカル探索** — 最近傍スナップ後に変換のみ焼きなまし等。
4. **（長期的）ルーティング埋め込み** — セグメント間を最短経路で埋める。

---

## 8. 実装ベースライン（現状）

### 8.1 コード配置

| パス | 役割 |
|---|---|
| `backend/app/optimization/constants.py` | `ROUTE_ARC_SAMPLES`、スケールクリップ域、評価重みの既定、`N_LOCAL_TRIALS_PER_GLOBAL` |
| `backend/app/optimization/defaults.py` | `AnnealOptions` の既定値（フロントの `optimizationDefaults.ts` と同値を保つこと） |
| `backend/app/optimization/types.py` | `Transform`, `OptimizeWeights`, `AnnealOptions`, `ScoreBreakdown`, `TraceStep`, `OptimizeResult`, `JointOptimizeResult` 等 |
| `backend/app/optimization/transform.py` | ストローク → グラフ内基準折れ線変換、`apply_transform`、`graph_center_m` 等 |
| `backend/app/optimization/snap_route.py` | 最近傍スナップ、smooth DP スナップ、Dijkstra フォールバック、折れ線連結 |
| `backend/app/optimization/scoring.py` | スナップ元評価・順序対応形状項・coverage 形状項・到達不能の加重和 |
| `backend/app/optimization/anneal.py` | `simulated_annealing_search`（シングル 1 試行）、`joint_simulated_annealing_search`（マルチコンポーネント 1 試行） |
| `backend/app/optimization/run.py` | `run_simulated_annealing`（シングル・マルチスタート）、`run_joint_simulated_annealing`（ジョイント・マルチスタート）、GeoJSON 化 |
| `backend/app/optimization/candidate_select.py` | トレース横断の `ranked_candidates` 選択 |
| `backend/app/debug/routes.py` | `POST /api/debug/optimize`（薄い層として上記を呼ぶ） |
| `backend/tests/test_optimization.py` | スモークテスト |

### 8.2 API（デバッグのみ）

**`POST /api/debug/optimize`**

#### リクエスト

グラフ入力（`graph-preview` と同型）に加えて:

```jsonc
{
  "stroke_components": [
    [{"x": 0.1, "y": 0.3}, ...],  // buildSinglePath 済み Point[]
    [{"x": 0.8, "y": 0.2}, ...]   // 1 件以上必須。2 件以上でジョイント SA
  ],
  "weights": { /* OptimizeWeightsBody */ },
  "anneal":  { /* AnnealOptionsBody  */ },
  "record_trace": true
}
```

`stroke_components` が空の場合は 400 エラー。1 件のとき `run_simulated_annealing`、2 件以上のとき `run_joint_simulated_annealing`。

#### `AnnealOptionsBody` フィールド

| フィールド | 既定 | 説明 |
|---|---|---|
| `optimization_budget_seconds` | 10.0 | 全試行の合計時間上限（秒） |
| `seed` | 0 | RNG シード |
| `max_iterations` | 250 | 試行ごとの最大反復数 |
| `restart_count` | 1 | 初期解（試行）の数 |
| `ignore_optimization_budget` | false | true のとき時間打ち切りなし |
| `ignore_source_rotation` | false | true のとき `source_rotation` 項を無視 |
| `initial_temperature` | 0.05 | 温度スケジュールの初期温度 |
| `final_temperature` | 0.001 | 温度スケジュールの最終温度 |
| `translation_step_m_ratio` | 0.08 | 並進摂動幅 ÷ グラフ span |
| `rotation_step_rad` | 0.35 | 回転摂動幅（ラジアン） |
| `log_scale_step` | 0.12 | 対数スケール摂動幅 |
| `trace_stride` | 5 | トレース記録間隔（ステップ数） |
| `step_scale_min` | 0.03 | 遷移幅スケールの下限（`temp_ratio` に比例、これ未満にはならない） |
| `max_display_candidates` | 5 | トレース横断で返す表示候補の上限 |
| `score_include_margin` | 0.05 | プール最良からこの絶対差以内のみ採用（1件だけでも可） |
| `candidate_diversity_min` | 0.12 | transform 空間での dedup 閾値 |

> **注意:** `n_local_trials`（後述）は現状 `AnnealOptionsBody` に公開されていない。バックエンド内部で `DEFAULT_N_LOCAL_TRIALS = 4` が使われる。

#### `OptimizeWeightsBody` フィールド

| フィールド | 既定 | 説明 |
|---|---|---|
| `source_rotation` | 0.38 | 入力の向きを保つ回転角ペナルティ |
| `source_scale` | 0.02 | `abs(log(scale))`（スケールずれ） |
| `shape_distance` | 1.0 | 順序対応距離 + coverage 距離（双方向） |
| `turn` | 0.0 | 旋回ペナルティ（現在は無効） |
| `unreachable` | 1e6 | 連結失敗ペナルティ |
| `out_of_graph` | 2.0 | グラフ bbox 外への逸脱ペナルティ |
| `dijkstra_fallback` | 0.3 | Dijkstra フォールバック率ペナルティ |
| `local_offset` | 0.5 | ローカルオフセットのノルムペナルティ（マルチコンポーネント時のみ有効） |

### 8.3 探索（焼きなまし）

#### シングルコンポーネント（`simulated_annealing_search`）

- **状態**: グローバル変換 `(theta_rad, scale, tx_m, ty_m)`。
- **遷移関数** `_propose_state`: translate / rotate / scale の中からランダムに 1 種（または 2 種の compound）を選び、Gaussian ノイズを加える。摂動幅は温度比に連動（`step_scale = max(step_scale_min, temp_ratio)`）。終盤の細探索は別フェーズの後処理ではなく、この 1 本の SA スケジュールで行う。
- **採択**: 改善は必ず採択。悪化は `exp(-delta / temperature)` で確率採択。温度は初期 → 最終へ幾何冷却。reheat 中は採択温度のみ `max(スケジュール温度, initial_temperature × 0.35)` に引き上げる（遷移幅 `step_scale` は変えない）。
- **Basin hopping**: 温度比 > 0.5 かつ確率 5% でランダム変換に飛ぶ。
- **停滞脱出**（`anneal.py` 内部定数、API 非公開）: `best` が `max(40, max(30, max_iterations // 5))` ステップ改善されない、かつ前回脱出から 25 ステップ以上経過したとき、通常 propose の代わりに `_random_transform` で完全ランダムジャンプを 1 回試す。発火後 12 ステップは reheat（採択温度ブースト）。`best` は常に保持するため、良い盆地に入った後の細探索挙動は従来どおり。`optimizer_meta` に `escape_triggers` / `reheat_steps_used` を restart 合算で記録。

#### マルチコンポーネント・ジョイント SA（`joint_simulated_annealing_search`）

- **状態**: グローバル変換 `(theta_rad, scale, tx_m, ty_m)` + コンポーネントごとのローカルオフセット `(dx_m, dy_m)`。
- **評価**: `apply_transform(base, global_t, center)` → 各コンポーネントに `(dx, dy)` を加算 → スナップ → `score_route`。スコアは弧長で正規化した加重平均 + ローカルオフセットペナルティ（`local_offset` 重み）。
- **遷移関数（ジョイント）**:
  1. `_propose_global_t`: グローバル変換のみを摂動（シングル SA と同じ move selection）。ローカルは動かさない。
  2. **n_local_trials**: その global 変換を固定したまま、ローカルオフセットを `n_local_trials`（既定 4）回独立にサンプル（各軸 `N(0, local_sigma)`, `local_sigma = max(span_x, span_y) * 0.02`）し、最良スコアを proposal として採択判定に使う。

  > **設計意図**: global 位置が良くても local offset の 1 サンプルが外れると不当に reject されていた問題を解消する（Rao-Blackwellization 的アプローチ）。`n_local_trials=1` にすれば従来と等価。

- **Basin hopping（ジョイント）**: ランダムな global 変換 + ゼロオフセット（ローカル trials なし）。
- **停滞脱出（ジョイント）**: シングル SA と同条件で `joint_score` の `best` 停滞時に global ランダムジャンプ + ローカルオフセットゼロ。reheat の採択温度ロジックも共通。

#### 共通

- **計算量管理**: `max_iterations` は各試行ごとにそのまま適用（試行数で割らない）。`optimization_budget_seconds` は全試行で共有し、時間切れの試行は途中打ち切り（`ignore_optimization_budget=true` のときは反復上限のみ）。
- **`optimizer_meta.search`**: `multistart_simulated_annealing`。

### 8.4 初期解生成（グリッド探索）

全試行の前に、`optimization_budget_seconds * 0.15` の時間を使って粗いグリッド探索を行い、スコア上位の変換を初期解候補とする（`run.py: _coarse_grid_search`）。

- 4×4 位置グリッド × 3 角度 × 3 スケール（log-uniform）= 最大 144 評価点（時間切れで打ち切り）
- 評価順は **角度 → 位置（グリッド中心に近い順）→ スケール（小→大）**。予算切れ時でも先頭で小・中・大スケールと内側位置を試す
- 多様性を保つ diversity-aware 選択で `restart_count` 個に絞る
- ジョイント SA では最大弧長のコンポーネントを基準にグリッド探索

### 8.5 ターゲット折れ線 → グラフ上ルート

1. 変換後の平面折れ線。
2. ノード空間 index から辺周辺のグラフ頂点を抽出。
3. 辺方向の射影順に DAG として扱い、角度ズレ・横方向ズレ・長さをコストに smooth DP。
4. 失敗時のみ区間 Dijkstra にフォールバック。
5. 到達不能はペナルティ。

### 8.6 スコア項（最小化）

| 項 | 説明 |
|---|---|
| `source_rotation` | 入力の向きを保ちたい場合の回転角ペナルティ。絶対角度 45° までは 0、超過分を `SOURCE_ROTATION_NORMALIZATION_DEG`（= 150°）で正規化。`ignore_source_rotation` で無効化可能。 |
| `source_scale` | `abs(log(scale))`（1 倍からの相対ズレ）。 |
| `shape_distance` | スナップ元とルートの双方向チャンファー距離（弧長順序対応 + coverage）。 |
| `turn` | 旋回ペナルティ。既定重みは 0（無効）。 |
| `unreachable` | 連結失敗時 1。 |
| `out_of_graph` | 変換後折れ線がグラフ bbox 外へ出た割合（SA の勾配として機能）。 |
| `dijkstra_fallback` | ルート構築で Dijkstra フォールバックした区間の割合。 |
| `local_offset`（ジョイントのみ） | ローカルオフセットの合計ノルム ÷ グラフ対角。相対位置のずれすぎを抑制する。 |

### 8.7 トレース

各試行ごとに以下を保存（`record_trace=true` のとき）:
- 初期 step、`trace_stride` ごとの step、best 更新 step。
- 各 step は `temperature`, `accepted`, `score_total`, `score_terms`, `transform`, `edge_ids` を持つ。
- **マルチコンポーネント時**: `edge_ids_per_component`（コンポーネントごとの edge_ids リスト）も付与される。

各試行 summary: `initial_transform`, `best_transform`, `best_score`, `best_breakdown`, `iterations_planned`, `iterations_completed`, `accepted_moves`, `acceptance_rate`, `deadline_hit`。

トレースの UI 表示・保存方法は [`debug.md`](./debug.md) を参照。

### 8.8 レスポンス（デバッグ）

```jsonc
{
  "trace_format_version": 2,
  "projection": { "lon0": ..., "lat0": ..., "mode": "local_tangent_plane" },
  "stats": { /* グラフ統計 */ },

  "candidates_geojson": { /* 採用候補ごとの LineString FeatureCollection */ },
  "ranked_candidates": [
    {
      "candidate_id": "r0_s42",
      "rank": 1,
      "score_total": 0.118,
      "score_delta_from_best": 0.0,
      "tier": "best",
      "route_length_km": 3.1,
      "labels": ["compact"],
      "transform": { ... },
      "score_terms": { ... }
    }
  ],
  "candidate_selection_meta": {
    "pool_size": 87,
    "after_quality_filter": 12,
    "score_include_margin": 0.05,
    "diversity_min": 0.12,
    "max_candidates": 5
  },
  "best_score": 0.123,
  "best_breakdown": { "shape_distance": ..., "source_rotation": ..., ... },
  "best_restart_index": 0,
  "route_length_m": 4200.0,
  "route_length_km": 4.2,
  "optimizer_meta": { "search": "multistart_simulated_annealing", ... },

  // 試行ごとの summary + trace
  "restarts": [
    {
      "restart_index": 0,
      "seed": 42,
      "initial_transform": { "tx_m": ..., "ty_m": ..., "theta_rad": ..., "scale": ... },
      "best_transform": { ... },
      "best_score": 0.123,
      "best_breakdown": { ... },
      "route_length_m": 4200.0,
      "route_length_km": 4.2,
      "iterations_planned": 250,
      "iterations_completed": 250,
      "accepted_moves": 87,
      "acceptance_rate": 0.348,
      "deadline_hit": false,
      "trace_steps": [ /* TraceStep[] */ ]
    }
  ],

  // コンポーネントごとのスコア内訳（シングルでも component_index=0 として返す）
  "components": [
    {
      "component_index": 0,
      "best_score": 0.11,
      "best_breakdown": { ... },
      "route_length_m": 2100.0,
      "route_length_km": 2.1
    },
    {
      "component_index": 1,
      "best_score": 0.14,
      "best_breakdown": { ... },
      "route_length_m": 2100.0,
      "route_length_km": 2.1
    }
  ]
}
```

### 8.9 フロント（デバッグ UI）

- [`DebugOptimizePanel.tsx`](../frontend/src/debug/components/DebugOptimizePanel.tsx): 焼きなましパラメータ入力、実行中の経過秒表示、**ランク付き候補セレクタ**（`ranked_candidates`）、ベスト試行と試行別 trace 表示、`processedComponents` の管理と送信ロジック。
- [`candidate_select.py`](../backend/app/optimization/candidate_select.py): 全 restart の `trace_steps` から品質フィルタ（`score_include_margin`）・transform dedup で `ranked_candidates` を構築（`tier`: `best` | `included`）。
- [`SinglePathDebugPreview.tsx`](../frontend/src/debug/components/SinglePathDebugPreview.tsx): 巡回順デバッグ表示（矢印・始終点・交点番号）。

### 8.10 あえて未実装／プロダクト要件との差

- 本番 UI 向けの複数候補比較（デバッグ API では `ranked_candidates` 対応済み）
- 本番用 `/api` エンドポイント（`/api/debug` のみ）
- 反転・一般アフィン変形（現状は回転・等方スケール・平行移動のみ）
- 許容幅付きの距離制約
- 移動モードに沿ったタグ解釈（Dijkstra は幾何距離のみ）
- 形状評価の追加候補（DTW / Fréchet）
- `n_local_trials` を UI から調整可能にする
- acceptance rate を使った温度・遷移幅の自動チューニング

---

## 9. 未決定・追記予定

- 徒歩／自転車／車などどの移動モードを第一にタグ解釈するか。
- 形状類似度と走行性の具体的な式と重み。
- 一筆書きをどの厳密さ（連続パスのみか、オイラー性までか）で課すか。

確定事項は時系列で `docs/decisions.md` に残し、本ファイルにも短く反映する。
