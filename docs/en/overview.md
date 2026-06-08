# Overview

Hand-drawn GPS Art Optimizer turns a sketched shape into a runnable route on real roads. Unlike tools that snap a shape drawn directly on the map, this app lets you draw freely on a canvas and then searches for where to place, rotate, and scale that shape within a map area.

## Pipeline

```
User sketch (strokes)
  → connected components + single-path conversion (frontend)
  → OSM fetch + road graph preprocessing (backend)
  → snap transformed shape to roads + score (backend)
  → multi-start simulated annealing over (tx, ty, θ, scale) (backend)
  → ranked route candidates + trace (API → map overlay)
```

See [article_visuals.html](article_visuals.html) for diagrams.

## Core design choice

The search state is **not** the route itself. It is the transform applied to the input polyline:

```
state = { tx_m, ty_m, theta_rad, scale }
```

For each candidate transform, the backend snaps the polyline to the road graph and scores the result. This keeps the search space low-dimensional (4D per component group) even when the road graph has tens of thousands of nodes.

Multi-component sketches (e.g. eyes and mouth) use **joint simulated annealing**: one shared global transform plus small per-component local offsets `(dx_m, dy_m)`.

## Production flow

1. User draws on the canvas and picks map center, fetch radius, and speed preset.
2. `POST /api/optimize` fetches OSM ways, builds a graph, runs optimization, returns GeoJSON routes.
3. The map shows ranked candidates; the user can replay the annealing trace.

## Key source locations

| Area | Path |
|------|------|
| Sketch input UI | `frontend/src/components/SketchModal.tsx` |
| Stroke → components | `frontend/src/lib/singlePathPostprocess.ts` |
| Production page | `frontend/src/pages/HomePage.tsx` |
| Production API | `backend/app/routes.py` |
| Optimization core | `backend/app/optimization/` |
| Graph preprocessing | `backend/app/preprocess/` |
| OSM fetch & ingest | `backend/app/osm/` |

## Related docs

- [Architecture](architecture.md)
- [Input preprocessing](input-preprocessing.md)
- [Road graph](road-graph.md)
- [Optimization](optimization.md)
