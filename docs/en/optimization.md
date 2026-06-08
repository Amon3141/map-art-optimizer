# Optimization

Multi-start simulated annealing searches over transform parameters, snapping the input polyline to the road graph at each step.

Implementation: `backend/app/optimization/`

## Production API

`POST /api/optimize` (`backend/app/routes.py`)

### Request

```json
{
  "stroke_components": [[{"x": 0.1, "y": 0.3}, ...], ...],
  "center_lon": 139.76,
  "center_lat": 35.68,
  "speed_preset": "normal",
  "fetch_radius_m": 2000,
  "ignore_source_rotation": false
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `speed_preset` | `"normal"` | `fast` \| `normal` \| `thorough` |
| `fetch_radius_m` | 2000 | Road fetch radius in meters |
| `ignore_source_rotation` | `false` | When `false`, penalize rotation away from the sketch orientation |

Speed presets (`backend/app/optimization/app_defaults.py`):

| Preset | Budget (s) | Restarts | Max iterations |
|--------|-------------|----------|----------------|
| fast | 5 | 2 | 300 |
| normal | 10 | 3 | 400 |
| thorough | 20 | 5 | 550 |

### Response (summary)

```json
{
  "candidates_geojson": { "type": "FeatureCollection", ... },
  "ranked_candidates": [{ "candidate_id": "...", "rank": 1, "score_total": 0.12, ... }],
  "best_score": 0.123,
  "route_length_km": 4.2,
  "restarts": [{ "trace_steps": [...], ... }],
  "components": [{ "component_index": 0, "best_score": ..., ... }]
}
```

- `record_trace` is always enabled in production
- `edges_geojson` is included for client-side trace replay

Routing logic (`backend/app/optimization/pipeline.py`):

- 1 component → `run_simulated_annealing`
- 2+ components → `run_joint_simulated_annealing`

## Transform model

Canvas strokes are converted to base polylines in meter space (`backend/app/optimization/transform.py`):

- Single component: `stroke_to_base_polyline_m`
- Multiple components: `strokes_to_base_polylines_m_shared` — shared scale from combined bounding box

Applied transform:

```
apply_transform(base_polyline, Transform(theta, scale, tx, ty), graph_center)
```

## Snapping

`backend/app/optimization/snap_route.py`:

1. Project transformed polyline segments onto nearby graph edges (spatial index)
2. For each segment, build a DAG of candidate nodes ordered by projection along the segment direction
3. Run smooth DP minimizing angle mismatch, lateral offset, and length cost
4. Fall back to Dijkstra between snap points when DP fails
5. Concatenate segment routes into one edge-id sequence

Snap runs on every annealing iteration, so spatial indexing and band-limited candidate sets are critical for performance.

## Scoring

Minimize weighted sum (`backend/app/optimization/scoring.py`, weights in `backend/app/optimization/constants.py`):

| Term | Meaning |
|------|---------|
| `shape_distance` | Bidirectional Chamfer-like distance between source polyline and snapped route |
| `source_rotation` | Penalty for rotating away from sketch orientation (0 below 45°, ramps to 150°) |
| `source_scale` | `abs(log(scale))` |
| `out_of_graph` | Fraction of transformed polyline outside graph bbox |
| `dijkstra_fallback` | Fraction of segments that needed Dijkstra fallback |
| `unreachable` | Large penalty when route construction fails |
| `local_offset` | Joint SA only: sum of per-component offset norms ÷ graph diagonal |

Default weights (`OptimizeWeights`): `shape_distance=1.0`, `source_rotation=0.38`, `source_scale=0.02`, `unreachable=1e6`, `out_of_graph=2.0`, `dijkstra_fallback=0.3`, `local_offset=0.5`.

## Simulated annealing

Core: `backend/app/optimization/anneal.py`, orchestration: `backend/app/optimization/run.py`

### Single-component state

```
{ tx_m, ty_m, theta_rad, scale }
```

- Propose: random choice among translate / rotate / scale (or compound); Gaussian noise; step size scales with temperature ratio
- Accept: always if improved; otherwise `exp(-Δ / T)` with geometric cooling
- Basin hopping: 5% chance of random jump when temperature ratio > 0.5
- Stagnation escape: random jump when best score stalls; temporary reheat on acceptance temperature

### Joint state (multi-component)

```
global_t: { tx_m, ty_m, theta_rad, scale }
local_offsets: [{ dx_m, dy_m }, ...]
```

- Global transform proposed as in single SA
- For each global proposal, sample `n_local_trials` (default 4) local offset vectors; use best score for acceptance
- Component scores are arc-length-weighted average + local offset penalty

### Initial solutions

Before restarts, `_coarse_grid_search` spends ~15% of budget on a 4×4 position × 3 angle × 3 scale grid (up to 144 evaluations). Diversity-aware selection picks `restart_count` starting transforms.

## Candidate selection

`backend/app/optimization/candidate_select.py` collects trace steps across all restarts, filters by score margin, deduplicates in transform space, and returns up to 5 `ranked_candidates`.

## Trace format

Each restart records `trace_steps` with: `temperature`, `accepted`, `score_total`, `score_terms`, `transform`, `edge_ids`, and (joint) `edge_ids_per_component`.

Frontend replay: `frontend/src/lib/routeOverlay.ts` — `overlayForCandidate`, `rebuildRouteForTraceStep`.

Shared UI: `AnnealingTraceSlider`, `RouteInfoPanel` in `frontend/src/components/`.

## Module map

| File | Role |
|------|------|
| `constants.py` | Score weights, arc sample count, scale clip bounds |
| `defaults.py` | Debug `AnnealOptions` defaults |
| `app_defaults.py` | Production speed presets, fetch radius, node limits |
| `types.py` | `Transform`, `TraceStep`, `OptimizeResult`, `JointOptimizeResult` |
| `transform.py` | Stroke → base polyline, `apply_transform` |
| `snap_route.py` | Snap + route construction |
| `scoring.py` | Route evaluation |
| `anneal.py` | Single and joint SA search (one restart each) |
| `run.py` | Multi-start orchestration, GeoJSON output |
| `serialize.py` | Response serialization |
| `pipeline.py` | End-to-end optimize pipeline |

## Related docs

- [Input preprocessing](input-preprocessing.md)
- [Road graph](road-graph.md)
- [Development](development.md) — debug API with full parameter control
