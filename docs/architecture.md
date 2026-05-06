# アーキテクチャ

## スタック

- **フロント**: Vite, React, TypeScript, Tailwind CSS, react-router-dom, MapLibre GL JS
- **バックエンド**: FastAPI, httpx（Overpass への非同期 HTTP）

## ディレクトリ

```
map-draw-optimizer/
  docs/
  frontend/     # Vite アプリ（左パネルは components/HomeSidebar.tsx）
  backend/      # FastAPI
```

## 環境変数

### frontend（`.env` / `.env.example`）

| 変数 | 説明 |
|------|------|
| `VITE_API_BASE` | バックエンドのオリジン（例: `http://127.0.0.1:8000`）。未設定時は相対パス `/api` を使用。開発中は Vite の `server.proxy` で `127.0.0.1:8000` に転送。 |
| `VITE_DEBUG` | `true` のときデバッグナビを表示 |

### backend（`.env`）

| 変数 | 説明 |
|------|------|
| `CORS_ORIGINS` | カンマ区切り（例: `http://localhost:5173`） |
| `OVERPASS_URL` | Overpass API のベース（例: `https://overpass-api.de/api/interpreter`） |

## 地図タイル

メイン地図は **ラスタタイル**（MapLibre）。利用規約・ポリシーは各タイルプロバイダに従う。

## OSM ベクタデータ

ブラウザから Overpass を直接叩くと **CORS** で失敗しやすいため、**FastAPI が Overpass にプロキシ**する。デバッグ用に件数上限を付与。

## 手書きストロークの簡略化

**Ramer–Douglas–Peucker**。キャンバス座標（ピクセル）上で許容誤差 `SIMPLIFY_TOLERANCE_PX`（[`frontend/src/lib/simplify.ts`](../frontend/src/lib/simplify.ts)、調整可）。確定後の点列は [`StrokePreview`](../frontend/src/components/StrokePreview.tsx) でサイドバーに縮小表示。

## Overpass 利用上の注意

公開インスタンスは負荷に弱い。**小さな bbox** と **件数上限** を守る。本番向けキャッシュは後続タスク。
