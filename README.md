# map-draw-optimizer

**手描きGPSアート** — 手描きの形と地図を扱うためのモノレポ（初期は UI と OSM 確認用 API のみ）。

## 必要なもの

- Node.js（プロジェクトでは Vite 8 を使用）
- Python 3.11+ 推奨

## 起動

### バックエンド

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 任意
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

テスト実行:

```bash
pytest
```

### フロントエンド

別ターミナルで:

```bash
cd frontend
npm install
cp .env.example .env        # 任意（開発 UI 用）
npm run dev
```

ブラウザで `http://localhost:5173` を開く。開発時は Vite が `/api` と `/health` を `http://127.0.0.1:8000` にプロキシする。

- メイン: `/`
- デバッグ: `/debug`（`VITE_APP_ENV=development` のときのみ。未設定の `vite dev` でも development）

詳細な共有用メモは [`docs/`](docs/) を参照。
