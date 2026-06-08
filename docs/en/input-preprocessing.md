# Input preprocessing

All stroke preprocessing runs in the browser before calling the API.

## Data model

Defined in `frontend/src/lib/strokeTypes.ts`:

```typescript
type InputMode = 'freehand' | 'pen' | 'text'

type StrokeData = {
  inputMode: InputMode
  strokes: Point[][]   // multiple strokes in draw order
}

const MAX_STROKE_POINTS = 150  // total points across all strokes
```

| Mode | Implementation |
|------|----------------|
| `freehand` | Free drawing; Ramer–Douglas–Peucker simplification on pointer up (`frontend/src/lib/simplify.ts`, tolerance `SIMPLIFY_TOLERANCE_PX`) |
| `pen` | Click-to-add polyline vertices with node snapping (`frontend/src/lib/penNodeSnap.ts`) |
| `text` | Glyph outlines via opentype.js (`frontend/src/lib/textToStrokes.ts`); development UI only |

## Processing pipeline

`strokesToProcessedComponents` in `frontend/src/lib/singlePathPostprocess.ts` runs when the user confirms a sketch:

```
strokes: Point[][]
  → findConnectedComponents(strokes)
  → for each component: buildSinglePath(componentStrokes)
  → processedComponents: Point[][]
  → POST /api/optimize { stroke_components: processedComponents }
```

- One component → single-component simulated annealing
- Two or more components → joint simulated annealing

## Connected components

`frontend/src/lib/strokeConnectivity.ts`:

- `segmentIntersectionParam` — segment intersection test with tolerance `GEOMETRY_EPS`
- `findConnectedComponents` — union-find over strokes connected by edge intersections

Strokes that do not touch are separate components (e.g. two eyes and a mouth).

## Single-path conversion (Chinese Postman)

`buildSinglePath` converts one connected component into a single continuous vertex list without adding edges that were not in the user's drawing.

Steps:

1. Detect intersections; split segments; build graph G = (V, E)
2. Find odd-degree vertices
3. All-pairs shortest paths between odd vertices (Dijkstra)
4. Minimum-weight matching on odd vertices (bitmask DP for k ≤ 20, greedy otherwise)
5. Add duplicate traversals of existing edges; extract Euler trail with Hierholzer
6. Compare PATH (start ≠ end) vs CIRCUIT (start = end); pick shorter output

**Constraint:** never insert a shortcut edge between disconnected parts of the sketch. Backtracking uses duplicate passes over existing edges only.

## API payload

```json
{
  "stroke_components": [
    [{"x": 0.1, "y": 0.3}, ...],
    [{"x": 0.8, "y": 0.2}, ...]
  ]
}
```

- `x`, `y` — normalized canvas coordinates
- Each array is already a single continuous path; the backend does not reorder vertices

## Related docs

- [Overview](overview.md)
- [Optimization](optimization.md)
