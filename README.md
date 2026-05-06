# map-draw-optimizer

**地図アート作成機** — 手描きの形と地図を扱うためのモノレポ（初期は UI と OSM 確認用 API のみ）。

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

### フロントエンド

別ターミナルで:

```bash
cd frontend
npm install
cp .env.example .env        # 任意（デバッグナビ用）
npm run dev
```

ブラウザで `http://localhost:5173` を開く。開発時は Vite が `/api` と `/health` を `http://127.0.0.1:8000` にプロキシする。

- メイン: `/`
- デバッグ: `/debug`（サイドバーからのリンクは `VITE_DEBUG=true` のときのみ）

詳細な共有用メモは [`docs/`](docs/) を参照。
