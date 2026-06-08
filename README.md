**English** | [日本語](README.ja.md)

# Hand-drawn GPS Art Optimizer

Draw a shape on a canvas and find a running route on nearby roads that follows it. The app fetches OpenStreetMap data, builds a road graph, and searches for a good placement (translation, rotation, scale) with multi-start simulated annealing.

**Live demo:** [gps-art.pages.dev](https://gps-art.pages.dev)

<img width="400" alt="Screen Recording 2026-05-23 at 10 37 58 PM (online-video-cutter com)" src="https://github.com/user-attachments/assets/937c6c70-904b-4b0f-8741-08133799acf7" />

## Setup

**Requirements:** Node.js (Vite 8), Python 3.11+

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run tests: `pytest`

### Frontend

In another terminal:

```bash
cd frontend
npm install
cp .env.example .env        # optional
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

Set `VITE_APP_ENV=development` to enable the text input tool, target-distance UI, and `/debug` page locally. Set `APP_ENV=development` on the backend to enable `/api/debug/*`.

## Documentation

[docs/](docs/README.md) — architecture, preprocessing, optimization, local development.

- [English](docs/en/)
- [日本語](docs/ja/)

Pipeline diagrams: [English](docs/en/article_visuals.html) · [日本語](docs/ja/article_visuals.html)
