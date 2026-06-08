# Architecture

## Stack

| Layer | Technologies |
|-------|-------------|
| Frontend | Vite, React, TypeScript, Tailwind CSS, MapLibre GL JS |
| Backend | FastAPI, httpx (Overpass proxy), Shapely (spatial indexing in preprocessing) |
| Data | OpenStreetMap via Overpass API |

## Repository layout

```
map-art-optimizer/
  frontend/          Vite app (production UI + optional debug UI)
  backend/           FastAPI (production + optional debug API)
  docs/              Technical documentation
  docs/en/article_visuals.html   Pipeline diagrams (English)
  docs/ja/article_visuals.html   Pipeline diagrams (Japanese)
```

### Frontend layers

- `frontend/src/components/` and `frontend/src/lib/` — shared code used by production and debug UIs
- `frontend/src/debug/` — debug-only components and utilities (must not be imported from shared code)

### Backend packages

| Package | Role |
|---------|------|
| `backend/app/routes.py` | Production `POST /api/optimize` |
| `backend/app/debug/` | Debug routes (`/api/debug/*`), registered only when `APP_ENV=development` |
| `backend/app/optimization/` | Simulated annealing, snapping, scoring |
| `backend/app/preprocess/` | Road graph preprocessing pipeline |
| `backend/app/osm/` | Overpass client, GeoJSON conversion, graph ingest |

## Deployment

The public demo runs at [gps-art.pages.dev](https://gps-art.pages.dev) (Cloudflare Pages for the frontend; backend hosted separately).

Production build:

```bash
cd frontend && npm run build    # output: frontend/dist/
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Set `VITE_API_BASE` at build time to point the frontend at the backend origin. The frontend ships with `frontend/public/_redirects` for SPA routing on Pages.

## Environment variables

### Frontend (`frontend/.env`)

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE` | Backend origin (e.g. `https://api.example.com`). Omit to use relative `/api`. |
| `VITE_APP_ENV` | `development` \| `production`. Default: `development` for `vite dev`, `production` for `vite build`. |

When `VITE_APP_ENV=production`: text input tool, target-distance UI, and `/debug` route are hidden.

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `OVERPASS_URL` | Overpass interpreter URL |
| `APP_ENV` | `development` enables `/api/debug/*`; `production` (default) disables them |

## API surface

| Endpoint | Availability | Purpose |
|----------|-------------|---------|
| `POST /api/optimize` | Always | Fetch roads, build graph, optimize |
| `GET /health` | Always | Health check |
| `POST /api/debug/*` | `APP_ENV=development` only | Graph preview, manual optimization tuning |

Production optimize is rate-limited to 10 requests/minute per IP (`backend/app/_limiter.py`).

## Map tiles & attribution

The map uses raster tiles via MapLibre. Tile provider terms apply. Road data attribution: © OpenStreetMap contributors.

## OSM data path

Browsers cannot call Overpass directly (CORS). The backend proxies Overpass requests. Production fetches only seven highway types (see [road-graph.md](road-graph.md)); debug mode can fetch all `highway=*` ways and filter client-side.

## Coordinate systems

- Canvas strokes use normalized coordinates in `[0, 1]`.
- Backend projects WGS84 to a local tangent plane centered on the map center (`backend/app/osm/projection.py`).
- API responses use GeoJSON with `[lon, lat]` coordinates.

## UI conventions

- Full-screen dialogs: `ModalShell` + React portal (`frontend/src/components/ModalShell.tsx`)
- Map overlays (route info, optimization progress): `absolute` positioning inside the map container in `HomePage.tsx`, not inside `MapPanel`
- z-index constants: `frontend/src/lib/modalLayers.ts`

## Related docs

- [Overview](overview.md)
- [Development](development.md)
