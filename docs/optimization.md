# 最適化（設計メモ）

**現状:** プロダクト用の本番 API は未着手だが、**デバッグ用にスナップ元のマルチスタート焼きなましが実装済み**（`backend/app/optimization/`、`POST /api/debug/optimize`）。要件・懸念・未決定のメモに加え、**セクション 8 に現行実装**を書く。確定判断の時系列は `docs/decisions.md` にも追記する。

---

## 1. この文書の位置づけ

| 書くこと | まだ書かないこと |
|----------|------------------|
| プロダクトとして満たしたい性質、制約、データの出所 | 本番向けの確定版としての性能保証 |
| API の形（GeoJSON 等）、`properties` の方針 | 評価関数の最終的な重み調整の結論 |
| 懸念（形の一致と走行性など） | 実装完了の保証や性能見積り |
| **セクション 8:** 現行ベースライン実装の要約 | 上記ベースライン以外の未実装範囲の細目 |

---

## 2. プロダクト上の狙い（最適化に関わる部分）

- **入力**: キャンバス上の**単一ストローク（手書き）のみ**。探索エリア内で **位置・回転・スケール** を調べ、道路ネット上で「絵」に近い**一連のルート**を探す。
- **出力**: **複数候補**をユーザーに提示できるようにする（ランキングや選択の余地）。
- **距離**: 目安として整数 km（**±2 km 程度**のゆるさは将来目標。実装段階で要検証）。

詳細のスコープ／非目標は `docs/product.md` を参照。

---

## 3. 要件（機能）

### 3.1 インプット（想定）

- フロントで **Douglas–Peucker 等により簡略化済みの点列**（キャンバス上の正規化座標など）、**探索エリア**（bbox または中心＋半径）、**距離の目安**。

### 3.2 アウトプット（API）

- **正（canonical）**: **GeoJSON `FeatureCollection`**（WGS84）。
- **ジオメトリ**: 候補ごとに **`LineString`**、座標は **`[経度, 緯度]`**。
- **候補と Feature の対応**: **ルート候補 1 本につき `Feature` を 1 つ**。

### 3.3 `properties` の方針

- **目的**: 最適化の**結果を追跡・デバッグ・UI 表示**に使う。スキーマの細目はアルゴリズム確定後に固める。
- **載せたい情報の例**（レベル感の合意のみ）:
  - 適用した幾何変換（例: 回転角、スケール、平行移動）
  - 評価スコア（定義はアルゴリズム依存）
  - ルート長（例: `length_km`、**単位を明示**）
- **検討課題**: `rank` / `candidate_id` の要否など。

### 3.4 地図・他フォーマットとの関係

- **Google マップ等での表示**: **折れ線オーバーレイ**（Directions API のルート形式に寄せる必要はない）。GeoJSON の `LineString` をクライアントで Polyline／Data レイヤに載せればよい。
- **KML / GPX**: **後処理で GeoJSON から変換可能**（`ogr2ogr`、言語別ライブラリなど）。座標は GeoJSON が `[lon, lat]`、KML は多くの場合 `lat,lon` 順なので変換時に注意。スタイルは別途。
- プロダクト上、GPX／KML の**製品仕様としての確定**はまだ先でも、**内部表現を GeoJSON に統一**しておけばエクスポートは差し替えやすい。

**GeoJSON → KML の後処理例（参考）**

- GDAL: `ogr2ogr -f KML out.kml in.geojson`
- Python: `fiona` / `geopandas` 等
- Node: GeoJSON → KML 用ライブラリ、または `LineString` を `<Placemark>` にマップ

---

## 4. 制約条件（考えるべき点）

### 4.1 道路ネットのみ

- **ルートは「地図上で通行可能な線」に沿う**必要がある（徒歩・自転車・走行のどれを主対象にするかは未確定）。
- **データの出所**: 本リポジトリでは **OpenStreetMap を Overpass で取得し、FastAPI がプロキシ**する方針（`docs/architecture.md`）。最適化バックエンドも同系統のデータをグラフ化して使う想定。
- **保持形式（イメージ）**: **グラフ**（交差点＝ノード、道路セグメント＝エッジ）。エッジに OSM の **`highway=*`** 等を載せ、許可する道路種別・ペナルティを後から調整できるようにする。
- **座標系**: 幾何計算（距離・スナップ・類似度）は **局所平面座標（メートル）** に投影してから行うと安定しやすい（実装詳細は未確定）。

### 4.2 「一筆書き」

- **意図**: ユーザーが描いたのと同様、**切れ目のない一本の連続パス**として表現されること。
- **厳しさの段階**: グラフ理論の **オイラー路・全域走査**まで要求すると制約が極端に硬くなる可能性がある。**初期スコープは「単一の連続パス（開いた線でよい）」**に寄せ、必要なら後から制約を強める、という切り分けを検討する。

### 4.3 距離

- ユーザー指定の**目標長さ**に対し、実際のグラフ上の長さが**許容範囲に入る**こと。閾値は実装・調整で決める。

---

## 5. 評価・目的関数まわりの懸念（重要）

### 5.1 「形が近い」と「走るのに適している」は別軸

- ヒューリスティックで**ターゲット形状に幾何的に近い**ルートが出ても、**現実に走りたいルート**とは限らない。
- **例**: 曲がり角が多すぎる、極端に細い道・非推奨タグの道を踏みすぎる、など。

→ **対策の方向性（未確定・併用可）**

- 目的関数を **複数項**に分ける（形状類似度、長さ違反ペナルティ、**旋回・曲がり角ペナルティ**、**道路種別コスト** 等）。
- または **段階的**: まず候補を生成し、**走行性でフィルタ／再ランキング**する。

### 5.2 完全一致より「人間の認識に近い柔軟さ」

- 人間はしばしば、**頂点の角度・辺の長さが少し違っても**、**つながりと大まかな配置**が同じなら**同じ形**として認識する。
- **ピクセル級・座標級に一致させすぎる**と、探索空間が狭くなり、**制約の中で歪んだだけのルート**になりやすい懸念がある。

→ **対策の方向性（未確定）**

- 形状類似度は **粗いサンプリング・トポロジ／順序を保った対応**・曲線距離（Fréchet / DTW 等）など、**過度に細かい一致を強制しない**設計を検討する。
- **認識（似ているか）**と**走行性**を**別レイヤ**で考え、あとで重み付けする発想。

---

## 6. メタヒューリスティック・探索の方向（確定ではない）

- **焼きなまし法をメインにする**案は、**状態と近傍の定義がはっきりすれば**現実的な候補の一つ。
- **状態**の例: 平面の **平行移動・回転・スケール** と、**道路グラフ上のパスやスナップ結果**の組み合わせ。
- **近傍**の例: 変換パラメータの摂動、別エッジ列への差し替え、など。
- **制約**（通行可能辺のみ・連続パス・長さ）は、**ペナルティ法**で緩く入れてから絞る手法も検討余地あり。

具体的な擬似コード・冷却スケジュールは **アルゴリズム選定後**に本ファイルまたは実装とともに追記する。**デバッグ用ベースラインの概要はセクション 8。**

---

## 7. 実装フェーズで試すアルゴリズムの方向性（メモ・未確定）

確定採用ではなく、**足がかり**として挙げていた案。

1. **離散探索（グリッド／サンプリング）** — 位置・角度・スケールを粗く総当たりし、スナップ後にスコア。デバッグしやすい。
2. **道路グラフ上の形状マッチング（粗い版）** — Fréchet / DTW、点とグラフの距離の和 等。
3. **貪欲スナップ＋ローカル探索** — 最近傍スナップ後に変換のみ焼きなまし等。
4. **（長期的）ルーティング埋め込み** — セグメント間を最短経路で埋める。グラフ基盤が整ってから。

**推奨進め方**: **小さい bbox・辺数が少ないデータ**で、**可視化・長さ制約・連続パス**が通るパイプラインを先に作り、評価項を段階的に足す。

---

## 8. 実装ベースライン（現状）

デバッグ検証用。スナップ元の状態 `(theta, scale, tx, ty)` を複数のランダム初期解から始める**マルチスタート焼きなまし**で遷移させ、各状態を smooth DP スナップ後に評価してベスト候補を 1 本返す。`docs/debug.md` の方針どおり **`app/optimization/` に本体**、`app/debug/routes.py` は薄い POST のみ。

### 8.1 コード配置

| パス | 役割 |
|------|------|
| `backend/app/optimization/constants.py` | `ROUTE_ARC_SAMPLES`、スケールクリップ域、評価重みの既定 |
| `backend/app/optimization/types.py` | `Transform`, `OptimizeWeights`, `AnnealOptions`, `ScoreBreakdown`, `TraceStep`, `OptimizeResult` |
| `backend/app/optimization/transform.py` | ストロークをグラフ内にフィットした基準折れ線 → 中心周りの回転・等方スケール・平行移動 |
| `backend/app/optimization/snap_route.py` | 最近傍スナップ、辺ごとの smooth DP スナップ、Dijkstra フォールバック、折れ線連結 |
| `backend/app/optimization/scoring.py` | スナップ元評価・順序対応形状項・coverage 形状項・到達不能の加重和 |
| `backend/app/optimization/anneal.py` | `simulated_annealing_search`（1 試行分の焼きなまし） |
| `backend/app/optimization/run.py` | `run_simulated_annealing`（マルチスタート orchestration）、GeoJSON 化 |
| `backend/tests/test_optimization.py` | スモーク |

### 8.2 API（デバッグのみ）

- **`POST /api/debug/optimize`**（[`backend/app/debug/routes.py`](backend/app/debug/routes.py)）
- リクエストは **`POST /api/debug/graph-preview` と同型**に加え、`stroke_points` を付与。
- 任意: `weights`, `anneal`, `record_trace`
  - `weights`: `source_rotation`, `source_scale`, `shape_distance`, `route_length`, `edge_count`, `turn`, `unreachable`
  - `anneal`: `optimization_budget_seconds`, `seed`, `max_iterations`, `restart_count`（初期解の数・試行数）, `ignore_source_rotation`, `initial_temperature`, `final_temperature`, `translation_step_m_ratio`, `rotation_step_rad`, `log_scale_step`, `trace_stride`
- サーバ内で `build_graph_from_geojson` を再度実行し、**同一条件なら `graph-preview` と同一 `RoadGraph`**。

### 8.3 探索（焼きなまし）

- **状態**: `theta_rad`, `scale`, `tx_m`, `ty_m`。
- **初期解**: 各試行ごとにランダム生成する。`theta` は `[-pi, pi]`、`scale` はクリップ範囲内の log-uniform、`tx/ty` はグラフ span に応じた範囲からサンプリングする。
- **遷移**: 回転・対数スケール・並進を小さく摂動する。遷移幅は温度に連動し、終盤ほど局所探索へ寄る。
- **採択**: 改善は必ず採択、悪化は `exp(-delta / temperature)` で採択する。温度は `initial_temperature` から `final_temperature` へ幾何冷却。
- **計算量管理**: `max_iterations` は**各試行（初期解）ごと**にそのまま適用する（試行数で割らない）。試行数を増やすと反復は概ね線形に増える。`optimization_budget_seconds` は全試行で共有し、時間切れの試行は途中で打ち切られる。
- **打ち切り**: 各試行では `max_iterations` または共有 `optimization_budget_seconds` の早い方。
- **`optimizer_meta.search`**: `multistart_simulated_annealing`。

### 8.4 ターゲット折れ線 → グラフ上ルート

1. 変換後の平面折れ線。2. ノード空間 index からスナップ元の各辺周辺のグラフ頂点を抽出。3. 辺方向の射影順に DAG として扱い、角度ズレ・横方向ズレ・長さをコストに smooth DP。4. 失敗時のみ区間 **Dijkstra** にフォールバック。5. 到達不能はペナルティ。

### 8.5 スコア（最小化）

| 項 | 意味（概要） |
|----|----------------|
| `source_rotation` | 入力の向きを保ちたい場合の回転角ペナルティ。絶対角度 30 度までは 0、超過分を `SOURCE_ROTATION_NORMALIZATION_DEG` で正規化する。`ignore_source_rotation` で無効化可能。 |
| `source_scale` | スナップ元のスケール評価。`abs(log(scale))`（1 倍からの相対ズレ）。 |
| `shape_distance` | スナップ元とルートの **弧長順序対応距離 + coverage 距離**（無次元化）。 |
| `route_length` | 実ルート長 ÷ bbox 対角。既定重みは 0 で、必要なら `weights` で上げる。 |
| `edge_count` | 辺数 ÷ `ROUTE_ARC_SAMPLES`。既定重みは 0。 |
| `turn` | 旋回ペナルティ（折れ角の正規化）。既定重みは 0。 |
| `unreachable` | 連結失敗時 1。 |

### 8.6 トレース

- 各試行ごとに、初期 step、`trace_stride` ごとの step、best 更新 step を保存する。各 step は `temperature`, `accepted`, `score_total`, `score_terms`, `transform`, `edge_ids` を持つ。
- 各試行の summary には `initial_transform`, `best_transform`, `best_score`, `best_breakdown`, `iterations_planned`, `iterations_completed`, `accepted_moves`, `acceptance_rate` を含める。

### 8.7 レスポンス（デバッグ）

- `candidates_geojson`, `best_score`, `best_breakdown`, `best_restart_index`, **`route_length_m` / `route_length_km`**（ベストルートのグラフ上幾何長・実距離）, `optimizer_meta`, `restarts[]`。
- `optimizer_meta` には `max_iterations_per_restart`（`anneal.max_iterations` を各試行にそのまま適用したときの計画反復数）などを含む。
- `restarts[]` は各試行の summary と `trace_steps[]` を持つ。旧 `steps[]` 互換は持たない。

### 8.8 フロント（デバッグ UI）

- [`DebugOptimizePanel.tsx`](frontend/src/debug/components/DebugOptimizePanel.tsx): 焼きなましの温度・反復数・初期解の数・角度無視・遷移幅オプション、実行中の経過秒表示、ベスト試行と試行別 trace 表示。

### 8.9 あえて未実装／プロダクト要件との差

- **複数候補のランキング提示**（現状はベスト 1 本のみ）。
- **複数候補の同時提示**（現状はマルチスタートの best 1 本のみを GeoJSON 表示）。
- **本番用 `/api` エンドポイント**（`/api/debug` のみ）。
- **反転・一般アフィン変形**（現状は回転・等方スケール・平行移動のみ）。
- **許容幅付きの距離制約**（±km 帯の完全な二段階最適化など）。
- **移動モードに沿ったタグ解釈**（Dijkstra は現状幾何距離のみ）。
- **オイラー路等の厳しい一筆書き制約**。
- **形状評価の追加候補**（DTW / Fréchet）。
- **`smooth_dp` の corridor 幅・コスト係数の調整しやすい定数化**。
- **複合 proposal / 試行ごとの初期分布の改善**。
- **acceptance rate を使った温度・遷移幅チューニング**。
- **空 route / 到達不能 route が多い場合の初期解生成・proposal 範囲制約改善**。

---

## 9. 未決定・`docs/decisions.md`／本ファイルへ追記するもの

- 徒歩／自転車／車など **どの移動モードを第一に**タグ解釈するか。
- **形状類似度**と**走行性**の具体的な式と重み。
- **一筆書き**をどの厳密さ（連続パスのみか、オイラー性までか）で課すか。

確定事項は時系列で `docs/decisions.md` に残し、本ファイルにも短く反映する。
