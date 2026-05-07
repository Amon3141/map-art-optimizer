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
| [frontend/src/debug/lib/](../frontend/src/debug/lib/) | デバッグ専用のユーティリティ・定数（例: 道路種別フィルタ、地図フィット）。 |

### 命名

- **`src/debug/components/`** のコンポーネントは **`Debug` で始まる名前**に統一する（例: `DebugSidebar`, `DebugWayList`）。
- 画面上・コード上の語は **OSM の線要素は way**、見た目としては **道路** とし、`highway` は **タグ名（`highway=*`）** のときだけ使う（クエリパラメータは `road_type`、エンドポイントは `/api/debug/ways`）。
- コンポーネントではないヘルパーは **`src/debug/lib/`** に置き、ファイル名で用途を示す（例: `fitMapToWay.ts`）。

### ホームからの導線

- [frontend/src/components/Sidebar.tsx](../frontend/src/components/Sidebar.tsx): `VITE_DEBUG=true` のときだけ `/debug` へのリンクを表示する。
- API のベース URL は `VITE_API_BASE`（デバッグページの説明文にも記載）。

## バックエンド

| 置き場 | 役割 |
| ------ | ---- |
| [backend/app/debug/](../backend/app/debug/) | **`/api/debug` 配下のルート**と、**そのレスポンスにしか使わない**処理のみ（例: テキストプレビュー用の要約、`/api/debug/ways` 用の道路種別ホワイトリスト）。 |
| [backend/app/osm/](../backend/app/osm/) | OSM 由来データの **本番前処理でも使う変換**（例: Overpass の way 要素 → GeoJSON FeatureCollection）。 |
| [backend/app/overpass/](../backend/app/overpass/) | Overpass API への問い合わせなど **プロダクト全体で共有しうるクライアント処理**。 |

`debug` パッケージのルートハンドラは、上記の **再利用モジュールを呼び出す薄い層** に留める。

### ルーター登録

- [backend/app/main.py](../backend/app/main.py): `app.include_router(debug_router, prefix="/api/debug", ...)`。`debug_router` は `app.debug` パッケージから import。

## 「検証完了 → 本番へ載せる」ときの流れ

1. ロジックは最初から **`app/osm/`・`app/overpass/` など適切な場所**に実装し、`app/debug/` から呼ぶ。
2. デバッグ専用の整形・ホワイトリスト・プレビュー文字列の切り詰めなどは **`app/debug/` にのみ**置く。
3. 本番 API を追加するときは、**同じ関数を import** してパイプラインに組み込む。デバッグ用コードを複製しない。

## 関連ドキュメント

- [preprocess.md](./preprocess.md) — H0 の段階（投影・グラフ化・索引など）と検証観点。
- [architecture.md](./architecture.md) — Overpass を FastAPI がプロキシする経路。
