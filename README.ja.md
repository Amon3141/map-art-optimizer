[English](README.md) | **日本語**

# 手描きGPSアート

キャンバスに描いた形を入力として、周辺の道路ネットワーク上でそれに近いランニングルートを探索します。OpenStreetMap の道路データを取得し、道路グラフを構築したうえで、平行移動・回転・スケールをマルチスタート焼きなましで最適化します。

**公開デモ:** [gps-art.pages.dev](https://gps-art.pages.dev)

<img width="400" alt="Screen Recording 2026-05-23 at 10 37 58 PM (online-video-cutter com)" src="https://github.com/user-attachments/assets/937c6c70-904b-4b0f-8741-08133799acf7" />

## セットアップ

**必要なもの:** Node.js（Vite 8）、Python 3.11 以上

### バックエンド

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 任意
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

テスト: `pytest`

### フロントエンド

別ターミナルで:

```bash
cd frontend
npm install
cp .env.example .env        # 任意
npm run dev
```

ブラウザで `http://localhost:5173` を開く。開発時は Vite が `/api` と `/health` を `http://127.0.0.1:8000` にプロキシする。

ローカルでテキスト入力・距離目安 UI・`/debug` ページを使うには、フロントに `VITE_APP_ENV=development`、バックエンドに `APP_ENV=development` を設定する。

## ドキュメント

[docs/](docs/README.md) — アーキテクチャ、前処理、最適化、ローカル開発。

- [English](docs/en/)
- [日本語](docs/ja/)

パイプライン図: [English](docs/en/article_visuals.html) · [日本語](docs/ja/article_visuals.html)
