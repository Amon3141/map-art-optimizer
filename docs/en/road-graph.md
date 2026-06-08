# Road graph

OSM highway ways are converted into a planar `RoadGraph` for snapping and routing.

## OSM fetch

Production (`POST /api/optimize` in `backend/app/routes.py`):

1. Compute bbox from map center + `fetch_radius_m` (1,000–5,000 m, default 2,000 m)
2. Query Overpass for ways with these `highway` values (`backend/app/osm/highway_include.py`):

   `trunk`, `primary`, `secondary`, `tertiary`, `unclassified`, `residential`, `service`

3. If way count exceeds `OVERPASS_MAX_WAYS` (`backend/app/preprocess/defaults.py`), keep the first N ways sorted by OSM way ID (no error)
4. If native node count exceeds `MAX_NATIVE_GRAPH_NODES` (35,000, `backend/app/optimization/app_defaults.py`), return HTTP 400 `graph_too_many_nodes`

Motorways and footways are excluded: motorways are not suitable for GPS art; footways are too numerous and often parallel carriageways.

## Projection

WGS84 coordinates are projected to a local tangent plane centered on the fetch origin (`backend/app/osm/projection.py`):

```
x = R · cos(lat0) · Δlon
y = R · Δlat
```

All distance, snap, and score calculations use meter coordinates in this plane.

## Ingest

`backend/app/osm/ingest.py` converts a GeoJSON FeatureCollection of LineStrings into a `RoadGraph`:

- Vertices with planar coordinates
- Edges with length, `highway` tag, OSM way metadata, and optional polyline geometry

## Preprocessing pipeline

`preprocess_road_graph` in `backend/app/preprocess/pipeline.py` applies optional steps in order:

| Step | Option flag | Production default |
|------|-------------|-------------------|
| Merge vertices sharing OSM node IDs | `connect_osm_node_ids_enabled` | ON |
| Snap nearby endpoints (ε threshold) | `snap_endpoints_enabled` | OFF |
| Merge parallel/duplicate road segments | `merge_duplicate_roads_enabled` | ON |
| Split edges at geometric intersections | `split_intersections_enabled` | OFF |
| Prune degree-2 chain vertices | `remove_redundant_chain_vertices_enabled` | ON |

Production uses defaults from `backend/app/preprocess/defaults.py` (connect + merge + prune only).

### Endpoint snap

When enabled (`backend/app/preprocess/options/snap_endpoints.py`): STRtree finds vertex pairs within ε; merges only when at least one vertex is a way endpoint and the pair is not both ends of the same edge.

### Intersection split

When enabled (`backend/app/preprocess/options/split_intersections.py`): STRtree enumerates segment bbox overlaps; splits edges at interior intersections so crossing roads become graph nodes.

### Duplicate road merge

When enabled (`backend/app/preprocess/options/merge_duplicate_roads.py`): STRtree finds parallel overlapping segments; union-find groups them; collapses to a representative corridor edge.

### Chain pruning

When enabled (`backend/app/preprocess/options/prune_chains.py`): removes degree-2 vertices on the same OSM way unless they represent meaningful curvature. Uses signed cumulative turn angle (default threshold ~10°) so gentle curves are preserved but noisy zig-zags are collapsed.

## Spatial indexing

Snap, split, and merge steps use Shapely STRtree for candidate filtering. The optimization snap step builds its own spatial index over graph edges.

## Graph output

After preprocessing, `graph_to_geojson_fc` produces node/edge FeatureCollections for visualization (debug) and internal use. The optimization pipeline receives the in-memory `RoadGraph`.

## Related docs

- [Architecture](architecture.md)
- [Optimization](optimization.md)
- [Development](development.md) — toggle preprocessing options in debug UI
