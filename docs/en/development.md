# Development

Local development can use a debug UI and API to inspect road graphs, preprocessing steps, and optimization traces.

## Enable debug mode

Set both:

```bash
# frontend/.env
VITE_APP_ENV=development

# backend/.env
APP_ENV=development
```

Then restart both servers. The home sidebar shows a link to `/debug`.

In production builds (`VITE_APP_ENV=production`, `APP_ENV=production`), `/debug` redirects to `/` and `/api/debug/*` is not registered.

## Debug page

`frontend/src/pages/Debug.tsx` — thin layout wiring, same pattern as `HomePage.tsx`.

| Path | Role |
|------|------|
| `frontend/src/debug/components/` | Debug-only React components (`Debug*` prefix) |
| `frontend/src/debug/lib/` | Debug utilities (highway filter, map fit, graph preview helpers) |

Workflow:

1. Fetch OSM ways in a bbox (`DebugSidebar`)
2. Preview the road graph with configurable preprocessing options
3. Draw a sketch and run optimization with full anneal/weight parameters (`DebugOptimizePanel`)
4. Inspect ranked candidates and replay trace steps on the map

## Debug API

Registered in `backend/app/debug/routes.py` when `APP_ENV=development`:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/debug/ways` | Fetch all `highway=*` ways in bbox (client filters display) |
| `POST /api/debug/graph-preview` | Build and visualize preprocessed graph |
| `POST /api/debug/optimize` | Run optimization on a provided graph + strokes |

`POST /api/debug/optimize` accepts the same optimization core as production but requires a pre-built graph and exposes all `AnnealOptions` and `OptimizeWeights` fields. See `backend/app/optimization/defaults.py`.

Debug mode has no `MAX_NATIVE_GRAPH_NODES` limit.

## Code organization rules

Shared code lives in `frontend/src/components/` and `frontend/src/lib/`. Debug code imports from shared layers; **never the reverse**.

Optimization logic lives in `backend/app/optimization/` and is imported by both production and debug routes. Do not duplicate algorithm code in `backend/app/debug/`.

## Trace replay offline

To reconstruct routes from a saved optimize response:

1. Save the optimize JSON response
2. Save the corresponding `graph-preview` response (`graph_geojson.edges` with `internal_edge_id`)
3. Use `edge_ids` from trace steps with `frontend/src/lib/routeOverlay.ts`

Same `seed` and request body reproduce server-side search deterministically (given the same code version).

## Tests

```bash
cd backend && pytest
```

Key test files: `test_optimization.py`, `test_preprocess.py`, `test_production_routes.py`.

## Related docs

- [Architecture](architecture.md)
- [Optimization](optimization.md)
- [Road graph](road-graph.md)
