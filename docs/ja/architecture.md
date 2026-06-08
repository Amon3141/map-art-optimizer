# アーキテクチャ

## スタック

| レイヤ | 技術 |
|--------|------|
| フロントエンド | Vite, React, TypeScript, Tailwind CSS, MapLibre GL JS |
| バックエンド | FastAPI, httpx（Overpass プロキシ）, Shapely（前処理の空間索引） |
| データ | OpenStreetMap（Overpass API 経由） |

## リポジトリ構成

```
map-art-optimizer/
  frontend/          Vite アプリ（本番 UI + 任意のデバッグ UI）
  backend/           FastAPI（本番 + 任意のデバッグ API）
  docs/              技術ドキュメント
  docs/en/article_visuals.html   パイプライン図（English）
  docs/ja/article_visuals.html   パイプライン図（日本語）
```

### フロントエンドのレイヤ

- `frontend/src/components/` と `frontend/src/lib/` — 本番・デバッグ共通コード
- `frontend/src/debug/` — デバッグ専用（共有コードから import しない）

### バックエンドパッケージ

| パッケージ | 役割 |
|-----------|------|
| `backend/app/routes.py` | 本番 `POST /api/optimize` |
| `backend/app/debug/` | デバッグルート（`APP_ENV=development` のときのみ `/api/debug/*` を登録） |
| `backend/app/optimization/` | 焼きなまし、スナップ、スコアリング |
| `backend/app/preprocess/` | 道路グラフ前処理パイプライン |
| `backend/app/osm/` | Overpass クライアント、GeoJSON 変換、グラフ取り込み |

## デプロイ

公開デモは [gps-art.pages.dev](https://gps-art.pages.dev)（フロントエンドは Cloudflare Pages、バックエンドは別ホスト）。

本番ビルド:

```bash
cd frontend && npm run build    # 出力: frontend/dist/
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

ビルド時に `VITE_API_BASE` でバックエンドのオリジンを指定する。SPA ルーティング用に `frontend/public/_redirects` を同梱している。

## 環境変数

### フロントエンド（`frontend/.env`）

| 変数 | 説明 |
|------|------|
| `VITE_API_BASE` | バックエンドのオリジン。未設定時は相対パス `/api`。 |
| `VITE_APP_ENV` | `development` \| `production`。`vite dev` では development、`vite build` では production が既定。 |

`VITE_APP_ENV=production` では、テキスト入力・距離目安 UI・`/debug` ルートを非表示にする。

### バックエンド（`backend/.env`）

| 変数 | 説明 |
|------|------|
| `CORS_ORIGINS` | 許可オリジン（カンマ区切り） |
| `OVERPASS_URL` | Overpass インタープリタ URL |
| `APP_ENV` | `development` で `/api/debug/*` を有効化。既定は `production` |

## API 一覧

| エンドポイント | 利用可否 | 用途 |
|---------------|---------|------|
| `POST /api/optimize` | 常時 | 道路取得・グラフ構築・最適化 |
| `GET /health` | 常時 | ヘルスチェック |
| `POST /api/debug/*` | `APP_ENV=development` のみ | グラフプレビュー、手動チューニング |

本番 optimize は IP あたり 10 回/分にレート制限（`backend/app/_limiter.py`）。

## 地図タイル・帰属

MapLibre でラスタタイルを表示。タイルプロバイダの利用規約に従う。道路データ: © OpenStreetMap contributors。

## OSM データの経路

ブラウザから Overpass を直接呼ぶと CORS で失敗するため、バックエンドがプロキシする。本番は 7 種の highway のみ取得（[road-graph.md](road-graph.md) 参照）。デバッグモードでは `highway=*` 全件を取得し、クライアント側でフィルタする。

## 座標系

- キャンバスストローク: `[0, 1]` の正規化座標
- バックエンド: 地図中心を原点とする局所接平面（`backend/app/osm/projection.py`）
- API レスポンス: GeoJSON `[lon, lat]`

## UI 規約

- 全画面ダイアログ: `ModalShell` + React portal（`frontend/src/components/ModalShell.tsx`）
- マップオーバーレイ（ルート情報・探索進捗）: `HomePage.tsx` の map コンテナ内に `absolute` 配置（`MapPanel` 内には置かない）
- z-index 定数: `frontend/src/lib/modalLayers.ts`

## 関連ドキュメント

- [概要](overview.md)
- [開発](development.md)
