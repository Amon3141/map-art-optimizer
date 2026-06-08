# 開発

ローカル開発では、道路グラフ・前処理・最適化トレースを確認できるデバッグ UI / API を使える。

## デバッグモードの有効化

以下を両方設定する:

```bash
# frontend/.env
VITE_APP_ENV=development

# backend/.env
APP_ENV=development
```

両サーバーを再起動すると、ホームサイドバーに `/debug` へのリンクが表示される。

本番ビルド（`VITE_APP_ENV=production`, `APP_ENV=production`）では `/debug` は `/` へリダイレクトし、`/api/debug/*` は登録されない。

## デバッグページ

`frontend/src/pages/Debug.tsx` — `HomePage.tsx` と同様に薄いレイアウト配線のみ。

| パス | 役割 |
|------|------|
| `frontend/src/debug/components/` | デバッグ専用 React コンポーネント（`Debug*` 接頭辞） |
| `frontend/src/debug/lib/` | デバッグユーティリティ（highway フィルタ、地図フィット、グラフプレビュー） |

ワークフロー:

1. bbox 内の OSM way を取得（`DebugSidebar`）
2. 前処理オプションを変えながら道路グラフをプレビュー
3. スケッチを描き、anneal/weight パラメータをフル指定で最適化（`DebugOptimizePanel`）
4. ランク付き候補とトレースステップを地図上で確認

## デバッグ API

`APP_ENV=development` のとき `backend/app/debug/routes.py` で登録:

| エンドポイント | 用途 |
|---------------|------|
| `GET /api/debug/ways` | bbox 内の `highway=*` way 全件取得（表示はクライアントでフィルタ） |
| `POST /api/debug/graph-preview` | 前処理済みグラフの構築・可視化 |
| `POST /api/debug/optimize` | 構築済みグラフ + ストロークで最適化 |

`POST /api/debug/optimize` は本番と同じ最適化コアを使うが、事前構築グラフが必要で、全 `AnnealOptions` / `OptimizeWeights` フィールドを公開する。詳細は `backend/app/optimization/defaults.py`。

デバッグモードには `MAX_NATIVE_GRAPH_NODES` 上限がない。

## コード配置ルール

共有コードは `frontend/src/components/` と `frontend/src/lib/` に置く。デバッグコードは共有レイヤから import する。**逆方向は禁止**。

最適化ロジックは `backend/app/optimization/` にあり、本番・デバッグ両ルートから import する。`backend/app/debug/` にアルゴリズムを複製しない。

## トレースのオフライン再生

保存した optimize レスポンスからルートを復元するには:

1. optimize JSON レスポンスを保存
2. 対応する `graph-preview` レスポンス（`internal_edge_id` 付き `graph_geojson.edges`）を保存
3. trace step の `edge_ids` と `frontend/src/lib/routeOverlay.ts` を使う

同一 `seed` とリクエストボディなら、同一コード版でサーバ側探索を再現できる。

## テスト

```bash
cd backend && pytest
```

主要テスト: `test_optimization.py`, `test_preprocess.py`, `test_production_routes.py`.

## 関連ドキュメント

- [アーキテクチャ](architecture.md)
- [最適化](optimization.md)
- [道路グラフ](road-graph.md)
