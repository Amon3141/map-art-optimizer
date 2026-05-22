# デバッグ UI・API の置き場と運用

このリポジトリでは、[docs/preprocess.md](./preprocess.md) で述べる **H0（道路グラフ前処理）** などを、本番フローとは切り離した **デバッグページと `/api/debug/*`** で検証する。

## 目的

- 実データ上で最適化アルゴリズムに使用する関数やロジックの挙動を確認する (前処理、ヒューリスティック、後処理、etc.)
- 検証したロジックは、そのままデバッグ専用に閉じ込めず、**再利用可能なモジュールに既に置いてあるものを本番パイプラインからも import** する（コピペで二重管理しない）。

デバッグ用エンドポイント・UI は **セキュリティ・運用上の理由から本番公開を前提にしない**想定（ローカルや限定環境）。

## フロントエンド

| 置き場 | 役割 |
| ------ | ---- |
| [frontend/src/pages/Debug.tsx](../frontend/src/pages/Debug.tsx) | ページのレイアウトと状態・イベントの配線のみ（[HomePage.tsx](../frontend/src/pages/HomePage.tsx) と同様に薄く保つ）。 |
| [frontend/src/debug/components/](../frontend/src/debug/components/) | デバッグ専用の React コンポーネント。 |
| [frontend/src/debug/lib/](../frontend/src/debug/lib/) | デバッグ専用のユーティリティ・定数（例: [`debugHighwayInclude.ts`](../frontend/src/debug/lib/debugHighwayInclude.ts) の highway 表示フィルタ、地図フィット）。 |

### 命名

- **`src/debug/components/`** のコンポーネントは **`Debug` で始まる名前**に統一する（例: `DebugSidebar`, `DebugWayList`）。
- 画面上・コード上の語は **OSM の線要素は way**、見た目としては **道路** とし、`highway` は **タグ名（`highway=*`）** のときだけ使う。`GET /api/debug/ways` は **bbox のみ**（クエリは緯度経度）で、Overpass から **その範囲の `highway` タグ付き way を全件**取得する。**どの highway 値を表示に含めるか**はデバッグ UI が **クライアント側**で GeoJSON をフィルタする（本番パイプラインとは別）。
- コンポーネントではないヘルパーは **`src/debug/lib/`** に置き、ファイル名で用途を示す（例: `fitMapToWay.ts`）。

### ホームからの導線

- [frontend/src/components/Sidebar.tsx](../frontend/src/components/Sidebar.tsx): `VITE_DEBUG=true` のときだけ `/debug` へのリンクを表示する。
- API のベース URL は `VITE_API_BASE`（デバッグページの説明文にも記載）。

## バックエンド

| 置き場 | 役割 |
| ------ | ---- |
| [backend/app/debug/](../backend/app/debug/) | **`/api/debug` 配下のルート**と、**そのレスポンスにしか使わない**処理のみ（例: テキストプレビュー用の要約、way 件数上限チェック）。 |
| [backend/app/optimization/](../backend/app/optimization/) | **最適化ロジック**（本番パイプラインからも import。`/api/debug/optimize` はここを呼ぶ薄い層）。 |
| [backend/app/osm/](../backend/app/osm/) | OSM 由来データの **本番前処理でも使う変換**（例: Overpass クライアント、way 要素 → GeoJSON FeatureCollection、GeoJSON → 道路グラフ取り込み）。 |
| [backend/app/preprocess/](../backend/app/preprocess/) | **投影済み `RoadGraph` 上の前処理**（オプション適用・型定義）。デバッグのグラフプレビューからも import。 |

`debug` パッケージのルートハンドラは、上記の **再利用モジュールを呼び出す薄い層** に留める。

### ルーター登録

- [backend/app/main.py](../backend/app/main.py): `app.include_router(debug_router, prefix="/api/debug", ...)`。`debug_router` は `app.debug` パッケージから import。

## 最適化（焼きなまし）のトレース・結果データとデバッグ

最適化アルゴリズムの**入出力の形**とスコアの定義は [optimization.md](./optimization.md) の「実装ベースライン」に書く。**ここでは「どう保存するか・どうデバッグするか」**（運用・UI）に限定する。

### サーバ側の保存

- **現状、サーバはレスポンスを永続化しない。** `POST /api/debug/optimize` は同期的に JSON を返すだけ（DB・ファイル出力なし）。
- 再現や共有のために残したい場合は、開発者側で **HTTP レスポンス全体をファイルに保存**する（例: ブラウザ開発者ツールの Network でレスポンスをコピー、`curl` の出力を `>` でリダイレクト、Playwright 等で取得）。

### レスポンスに含まれるもの（保存時の単位）

- **`candidates_geojson`**: 全ランク候補の WGS84 `LineString` を `candidate_id` プロパティ付きで含む `FeatureCollection`。`overlayForCandidate`（`lib/routeOverlay.ts`）で候補 ID をフィルタして表示する。
- **`restarts`**: 試行ごとの summary と `trace_steps`。ここでいう試行は、ランダムに作った別々の初期解から焼きなましを始める 1 回分の探索。**各ステップはジオメトリを持たず**、`edge_ids`（`internal_edge_id` の列）と `transform`・スコア・温度・採択有無のみ。マルチコンポーネント時は `edge_ids_per_component`（コンポーネントごとの edge_ids）も付与される。summary には `initial_transform`, `best_score`, `best_breakdown`, `acceptance_rate` などを含む。
- **`components`**: コンポーネントごとの `best_score`, `best_breakdown`, `route_length_m`。シングルコンポーネント時も `component_index=0` として返す。
- **`best_restart_index`**: 全試行のうち、最良スコアを出した試行。
- **`trace_format_version`**: 現状 `2`。クライアントや後処理スクリプトは、この番号でスキーマ互換を判断できるようにする（形式変更時はバージョンを上げる）。

### フロント（デバッグページ）でのデバッグ

1. **前処理フロー**で道路を取得し、グラフモードで `graph-preview` が成功した状態にする（[`DebugSidebar`](../frontend/src/debug/components/DebugSidebar.tsx)）。
2. **「このグラフで形を探索」**で最適化サイドバー（[`DebugOptimizePanel`](../frontend/src/debug/components/DebugOptimizePanel.tsx)）へ遷移。
3. 手書きストローク・評価モード・探索設定（`anneal` は [optimization.md](./optimization.md) 8.2 の公開フィールドのみ）を入れ、**実行**。同期 API なのでサーバから逐次進捗は返さないが、UI は経過秒・時間上限・最大反復数（試行ごと）・初期解の数を表示する。結果は **ページの React 状態にのみ保持**（リロードで消える）。
4. **マップ上の表示**
   - **ベスト候補**: `overlayForCandidate`（`lib/routeOverlay.ts`）で `candidates_geojson` から候補 ID をフィルタしてオーバーレイ。
   - **試行 / トレーススライダー**: `restarts[n].trace_steps[i].edge_ids` と、直前の **`graph-preview` の edges FeatureCollection**（`properties.internal_edge_id`）を組み合わせ、クライアントで WGS84 の折れ線を復元（[`routeOverlay.ts`](../frontend/src/lib/routeOverlay.ts)）。  
     → トレースを見るには **同じセッションで取得済みのグラフ GeoJSON** が必要。保存した JSON だけでは、edges が別途必要。
   - **マルチコンポーネント**: `trace_steps[i].edge_ids_per_component` を使うと、コンポーネントごとに色分けして表示できる。`edge_ids`（結合版）は後退互換のため残す。

### オフラインでトレースを再現するとき

- 保存物に **`optimize` の JSON** と、対応する **`graph-preview` 応答の `graph_geojson.edges`**（および投影 `lon0`/`lat0` が分かること）があれば、`edge_ids` からルート線を復元できる。
- **`seed` とリクエストボディが同じ**なら、実装が変わらない限りサーバ上の探索は再現可能（デバッグ用の決定性）。

### 本番との境界

- トレースの冗長保存・長期保管・ユーザー向けエクスポートは **本番仕様としては未着手**。必要になったら `app/optimization/` の結果型を流用しつつ、保存先と PII 方針（`product.md` のメモ）を決めてから `app/debug` 以外に載せる。

## 「検証完了 → 本番へ載せる」ときの流れ

1. ロジックは最初から **`app/osm/`・`app/preprocess/` など適切な場所**に実装し、`app/debug/` から呼ぶ。
2. デバッグ専用の整形・ホワイトリスト・プレビュー文字列の切り詰めなどは **`app/debug/` にのみ**置く。
3. 本番 API を追加するときは、**同じ関数を import** してパイプラインに組み込む。デバッグ用コードを複製しない。

## 関連ドキュメント

- [preprocess.md](./preprocess.md) — H0 の段階（投影・グラフ化・索引など）と検証観点。
- [optimization.md](./optimization.md) — 最適化の要件・実装ベースライン（API フィールド・スコア項など）。**トレースの保存・UI での見方は本文書の「最適化（焼きなまし）のトレース・結果データとデバッグ」**。
- [input_shape.md](./input_shape.md) — 入力形状の前処理（一筆書き化・connected components・バックエンドへの送信フォーマット）。
- [architecture.md](./architecture.md) — Overpass を FastAPI がプロキシする経路。
