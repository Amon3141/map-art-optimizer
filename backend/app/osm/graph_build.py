"""
OSM way 折れ線から平面グラフへの変換パイプライン。

処理順（既定）:
1. 重複ジオメトリ除去（オプション）
2. ネイティブトポロジ（way 内の連続頂点間エッジ）
3. OSM node id による接続（オプション）
4. 道路交差の幾何 split（オプション）
5. 距離ベース snap（オプション）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .graph_model import InternalEdge, InternalNode, RoadGraph
from .projection import lon_lat_to_xy_m, xy_m_to_lon_lat


@dataclass
class GraphBuildOptions:
    deduplicate_geometry: bool = False
    connect_osm_node_ids: bool = False
    snap_endpoints: bool = False
    snap_epsilon_m: float = 5.0
    split_intersections: bool = False


@dataclass
class WayPolyline:
    osm_way_id: int
    highway: str | None
    coords_lonlat: list[tuple[float, float]]
    osm_node_ids: list[int]


@dataclass
class GraphBuildResult:
    graph: RoadGraph
    lon0: float
    lat0: float
    explanation_lines: list[str]
    stats: dict[str, Any]
    step_metrics: dict[str, Any]
    dedupe_removed_edges_geojson: dict[str, Any] = field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )
    dedupe_removed_vertices_geojson: dict[str, Any] = field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )


# --- geometry primitives (meters) ---
SEG_PT_TOL_M = 0.05
PARALLEL_EPS = 1e-12
MAX_SPLIT_ITER = 2000

PILE_LONLAT_DECIMALS = 5

# 交差探索グリッド: bbox 短辺をこの分割数で割ったセル（下限あり）
_SPLIT_GRID_DIVISIONS = 64
_SPLIT_CELL_MIN_M = 2.0
# セル内候補が多すぎるときのフォールバック（同一セル内のみ全対全）
_SPLIT_CELL_DENSE_THRESHOLD = 256


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def segment_intersection_interior(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """両セグメントの真の内部で交わる唯一の点を返す（端は除外）。"""
    eps_t = 1e-9
    r = _sub(b, a)
    s = _sub(d, c)
    denom = _cross(r[0], r[1], s[0], s[1])
    if abs(denom) < PARALLEL_EPS:
        return None
    qp = _sub(c, a)
    t = _cross(qp[0], qp[1], s[0], s[1]) / denom
    u = _cross(qp[0], qp[1], r[0], r[1]) / denom
    if t <= eps_t or t >= 1.0 - eps_t:
        return None
    if u <= eps_t or u >= 1.0 - eps_t:
        return None
    return (a[0] + t * r[0], a[1] + t * r[1])


def nearest_point_on_segment(
    q: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    vx, vy = _sub(b, a)
    len2 = vx * vx + vy * vy
    if len2 < 1e-18:
        return a, 0.0
    t = ((_sub(q, a)[0]) * vx + (_sub(q, a)[1]) * vy) / len2
    t = max(0.0, min(1.0, t))
    return (a[0] + t * vx, a[1] + t * vy), t


# --- uniform spatial grid (H0-e: preprocess.md) ---
# snap: cell_m = snap_epsilon_m（ε 以内の点対は同一セルまたは8近傍に収まる）
# split: cell_m = max(bbox_short_side / N, floor_m) で長辺は複数セルに登録


def _grid_cell_xy(x: float, y: float, cell_m: float) -> tuple[int, int]:
    return (math.floor(x / cell_m), math.floor(y / cell_m))


def _segment_aabb(
    p0: tuple[float, float], p1: tuple[float, float], pad: float = 0.0
) -> tuple[float, float, float, float]:
    x0, y0 = p0
    x1, y1 = p1
    xmin = min(x0, x1) - pad
    xmax = max(x0, x1) + pad
    ymin = min(y0, y1) - pad
    ymax = max(y0, y1) + pad
    return xmin, xmax, ymin, ymax


def _iter_cell_rect(
    xmin: float, xmax: float, ymin: float, ymax: float, cell_m: float
) -> list[tuple[int, int]]:
    if cell_m <= 0:
        return []
    ix0 = math.floor(xmin / cell_m)
    ix1 = math.floor(xmax / cell_m)
    iy0 = math.floor(ymin / cell_m)
    iy1 = math.floor(ymax / cell_m)
    out: list[tuple[int, int]] = []
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            out.append((ix, iy))
    return out


def _cells_for_segment(
    a: tuple[float, float], b: tuple[float, float], cell_m: float
) -> list[tuple[int, int]]:
    xmin, xmax, ymin, ymax = _segment_aabb(a, b)
    return _iter_cell_rect(xmin, xmax, ymin, ymax, cell_m)


def _index_edge_segments_by_cell(
    graph: RoadGraph, cell_m: float
) -> dict[tuple[int, int], list[tuple[str, int]]]:
    """各セルに、その bbox と交わる (edge_id, seg_i) を列挙。"""
    cell_map: dict[tuple[int, int], list[tuple[str, int]]] = {}
    for eid, e in graph.edges.items():
        pl = e.polyline_xy_m
        if len(pl) < 2:
            continue
        for seg_i in range(len(pl) - 1):
            a, b = pl[seg_i], pl[seg_i + 1]
            for key in _cells_for_segment(a, b, cell_m):
                cell_map.setdefault(key, []).append((eid, seg_i))
    return cell_map


def _split_grid_cell_m(graph: RoadGraph) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for e in graph.edges.values():
        for px, py in e.polyline_xy_m:
            xs.append(px)
            ys.append(py)
    if not xs:
        return _SPLIT_CELL_MIN_M
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    short_side = max(min(span_x, span_y), _SPLIT_CELL_MIN_M)
    return max(short_side / _SPLIT_GRID_DIVISIONS, _SPLIT_CELL_MIN_M)


# --- GeoJSON parsing ---


def parse_way_features(geojson_fc: dict[str, Any]) -> list[WayPolyline]:
    feats = geojson_fc.get("features") or []
    out: list[WayPolyline] = []
    if not isinstance(feats, list):
        return out
    for f in feats:
        if not isinstance(f, dict):
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        props = f.get("properties") or {}
        wid_raw = props.get("osm_way_id")
        if wid_raw is None:
            continue
        wid = int(wid_raw)
        hw = props.get("highway")
        highway = str(hw) if hw is not None else None
        ll: list[tuple[float, float]] = []
        for c in coords:
            if not isinstance(c, (list, tuple)) or len(c) < 2:
                continue
            ll.append((float(c[0]), float(c[1])))
        if len(ll) < 2:
            continue
        nids_raw = props.get("osm_node_ids")
        if not isinstance(nids_raw, list) or len(nids_raw) != len(ll):
            continue
        try:
            nids = [int(x) for x in nids_raw]
        except (TypeError, ValueError):
            continue
        out.append(WayPolyline(osm_way_id=wid, highway=highway, coords_lonlat=ll, osm_node_ids=nids))
    return out


def dedupe_geometry_ways(ways: list[WayPolyline]) -> list[WayPolyline]:
    """連続する同一座標の除去、および連続する同一 OSM node id の折り畳み。"""
    cleaned: list[WayPolyline] = []
    for w in ways:
        c_list: list[tuple[float, float]] = []
        n_list: list[int] = []
        for i, (lon, lat) in enumerate(w.coords_lonlat):
            nid = w.osm_node_ids[i]
            if c_list and abs(c_list[-1][0] - lon) < 1e-9 and abs(c_list[-1][1] - lat) < 1e-9:
                continue
            if n_list and n_list[-1] == nid and c_list:
                continue
            c_list.append((lon, lat))
            n_list.append(nid)
        if len(c_list) >= 2:
            cleaned.append(
                WayPolyline(
                    osm_way_id=w.osm_way_id,
                    highway=w.highway,
                    coords_lonlat=c_list,
                    osm_node_ids=n_list,
                )
            )
    return cleaned


def dedupe_removed_geometry_geojson(ways: list[WayPolyline]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    dedupe_geometry_ways と同じ規則で「折り畳まれた」セグメントと除去された頂点を GeoJSON にする。
    オリジナル折れ線上で clean_idx[i+1] != clean_idx[i] + 1 のセグメントを除去ジオメトリとみなす。
    """
    edge_feats: list[dict[str, Any]] = []
    vert_feats: list[dict[str, Any]] = []
    eps = 1e-9
    for w in ways:
        coords = w.coords_lonlat
        nids = w.osm_node_ids
        n = len(coords)
        if n < 2:
            continue
        c_list: list[tuple[float, float]] = []
        n_list: list[int] = []
        clean_pos: list[int] = []
        skipped: list[bool] = []
        for i, (lon, lat) in enumerate(coords):
            nid = nids[i]
            dup_coord = bool(
                c_list and abs(c_list[-1][0] - lon) < eps and abs(c_list[-1][1] - lat) < eps
            )
            dup_nid = bool(n_list and n_list[-1] == nid and c_list)
            if dup_coord or dup_nid:
                skipped.append(True)
                clean_pos.append(len(c_list) - 1)
                continue
            skipped.append(False)
            c_list.append((lon, lat))
            n_list.append(nid)
            clean_pos.append(len(c_list) - 1)
        for i in range(n - 1):
            ci = clean_pos[i]
            cj = clean_pos[i + 1]
            if cj != ci + 1:
                p0 = coords[i]
                p1 = coords[i + 1]
                if abs(p0[0] - p1[0]) > 1e-12 or abs(p0[1] - p1[1]) > 1e-12:
                    edge_feats.append(
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[p0[0], p0[1]], [p1[0], p1[1]]],
                            },
                            "properties": {"osm_way_id": w.osm_way_id},
                        }
                    )
        for i in range(n):
            if skipped[i]:
                lon, lat = coords[i]
                vert_feats.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {"osm_way_id": w.osm_way_id, "osm_node_id": nids[i]},
                    }
                )
    return (
        {"type": "FeatureCollection", "features": edge_feats},
        {"type": "FeatureCollection", "features": vert_feats},
    )


def build_native_graph(
    ways: list[WayPolyline],
    project: Callable[[float, float], tuple[float, float]],
) -> RoadGraph:
    nodes: dict[str, InternalNode] = {}
    edges: dict[str, InternalEdge] = {}
    for w in ways:
        wid = w.osm_way_id
        ncoords = len(w.coords_lonlat)
        for i, (lon, lat) in enumerate(w.coords_lonlat):
            nid = f"native:{wid}:{i}"
            x_m, y_m = project(lon, lat)
            is_ep = i == 0 or i == ncoords - 1
            nodes[nid] = InternalNode(
                id=nid,
                x_m=x_m,
                y_m=y_m,
                source_osm_node_ids=[w.osm_node_ids[i]],
                is_way_polyline_endpoint=is_ep,
                merged_from_snap=False,
                merged_from_osm_id=False,
            )
        for i in range(ncoords - 1):
            u = f"native:{wid}:{i}"
            v = f"native:{wid}:{i + 1}"
            eid = f"e:{wid}:{i}"
            pu = (nodes[u].x_m, nodes[u].y_m)
            pv = (nodes[v].x_m, nodes[v].y_m)
            edges[eid] = InternalEdge(
                id=eid,
                u=u,
                v=v,
                polyline_xy_m=[pu, pv],
                osm_way_id=wid,
                highway=w.highway,
            )
    return RoadGraph(nodes=nodes, edges=edges)


def _merge_source_ids(lists: list[list[int]]) -> list[int]:
    s: set[int] = set()
    for lst in lists:
        for x in lst:
            s.add(x)
    return sorted(s)


def collapse_nodes(
    graph: RoadGraph,
    cluster: list[str],
    *,
    merge_kind: Literal["osm_id", "snap"] | None = None,
) -> int:
    """Returns number of nodes removed from graph (0 if no collapse)."""
    if len(cluster) < 2:
        return 0
    canonical = min(cluster)
    xs = sum(graph.nodes[k].x_m for k in cluster) / len(cluster)
    ys = sum(graph.nodes[k].y_m for k in cluster) / len(cluster)
    src = _merge_source_ids([graph.nodes[k].source_osm_node_ids for k in cluster])
    ep_any = any(graph.nodes[k].is_way_polyline_endpoint for k in cluster)
    snap_any = merge_kind == "snap" or any(graph.nodes[k].merged_from_snap for k in cluster)
    osm_merge_any = merge_kind == "osm_id" or any(graph.nodes[k].merged_from_osm_id for k in cluster)
    others = {n for n in cluster if n != canonical}
    graph.nodes[canonical] = InternalNode(
        id=canonical,
        x_m=xs,
        y_m=ys,
        source_osm_node_ids=src,
        is_way_polyline_endpoint=ep_any,
        merged_from_snap=snap_any,
        merged_from_osm_id=osm_merge_any,
    )
    for o in others:
        del graph.nodes[o]
    remap = {k: canonical for k in cluster}
    new_edges: dict[str, InternalEdge] = {}
    for eid, e in graph.edges.items():
        u = remap.get(e.u, e.u)
        v = remap.get(e.v, e.v)
        if u == v:
            continue
        pl = list(e.polyline_xy_m)
        if pl:
            pl[0] = (graph.nodes[u].x_m, graph.nodes[u].y_m)
            pl[-1] = (graph.nodes[v].x_m, graph.nodes[v].y_m)
        new_edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=pl,
            osm_way_id=e.osm_way_id,
            highway=e.highway,
        )
    graph.edges = new_edges
    return len(others)


def merge_by_osm_node_id(graph: RoadGraph) -> dict[str, Any]:
    """
    同一 OSM node id を共有するグラフ頂点を union-find でまとめ、一括で remap する。
    osm_id_groups_merged は「重複があった OSM id」の数（初期グラフ上）。
    """
    groups: dict[int, list[str]] = {}
    for nid, node in graph.nodes.items():
        for osm_id in node.source_osm_node_ids:
            groups.setdefault(osm_id, []).append(nid)
    osm_id_groups_merged = sum(1 for _oid, members in groups.items() if len(set(members)) >= 2)

    parent = {n: n for n in graph.nodes}
    for _oid, members in groups.items():
        uniq = sorted(set(members))
        if len(uniq) < 2:
            continue
        base = uniq[0]
        for other in uniq[1:]:
            _uf_union(parent, base, other)

    clusters: dict[str, list[str]] = {}
    for nid in graph.nodes:
        r = _uf_find(parent, nid)
        clusters.setdefault(r, []).append(nid)

    rem: dict[str, str] = {}
    merged_canonical: dict[str, InternalNode] = {}
    vertices_removed = 0
    for _root, members in clusters.items():
        canonical = min(members)
        for k in members:
            rem[k] = canonical
        if len(members) < 2:
            continue
        vertices_removed += len(members) - 1
        xs = sum(graph.nodes[k].x_m for k in members) / len(members)
        ys = sum(graph.nodes[k].y_m for k in members) / len(members)
        src = _merge_source_ids([graph.nodes[k].source_osm_node_ids for k in members])
        ep_any = any(graph.nodes[k].is_way_polyline_endpoint for k in members)
        snap_any = any(graph.nodes[k].merged_from_snap for k in members)
        osm_merge_any = True
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=snap_any,
            merged_from_osm_id=osm_merge_any,
        )

    final_nodes: dict[str, InternalNode] = {}
    for nid, node in graph.nodes.items():
        if rem[nid] != nid:
            continue
        if nid in merged_canonical:
            final_nodes[nid] = merged_canonical[nid]
        else:
            final_nodes[nid] = InternalNode(
                id=nid,
                x_m=node.x_m,
                y_m=node.y_m,
                source_osm_node_ids=list(node.source_osm_node_ids),
                is_way_polyline_endpoint=node.is_way_polyline_endpoint,
                merged_from_snap=node.merged_from_snap,
                merged_from_osm_id=node.merged_from_osm_id,
            )

    new_edges: dict[str, InternalEdge] = {}
    for eid, e in graph.edges.items():
        u = rem[e.u]
        v = rem[e.v]
        if u == v:
            continue
        pl = list(e.polyline_xy_m)
        if pl:
            nu = final_nodes[u]
            nv = final_nodes[v]
            pl[0] = (nu.x_m, nu.y_m)
            pl[-1] = (nv.x_m, nv.y_m)
        new_edges[eid] = InternalEdge(
            id=eid,
            u=u,
            v=v,
            polyline_xy_m=pl,
            osm_way_id=e.osm_way_id,
            highway=e.highway,
        )
    graph.nodes = final_nodes
    graph.edges = new_edges
    return {
        "osm_id_groups_merged": osm_id_groups_merged,
        "graph_vertices_removed_by_merge": vertices_removed,
    }


def _uf_find(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _uf_union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra != rb:
        parent[rb] = ra


def snap_endpoints(graph: RoadGraph, epsilon_m: float) -> dict[str, Any]:
    """ε 近傍の頂点を union。セルサイズ = ε（同一・隣接セルに候補が収まる）。"""
    cell_m = max(epsilon_m, 1e-6)
    cell_nodes: dict[tuple[int, int], list[str]] = {}
    for nid, n in graph.nodes.items():
        key = _grid_cell_xy(n.x_m, n.y_m, cell_m)
        cell_nodes.setdefault(key, []).append(nid)

    parent = {n: n for n in graph.nodes}
    for nid in graph.nodes:
        na = graph.nodes[nid]
        ix, iy = _grid_cell_xy(na.x_m, na.y_m, cell_m)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for oid in cell_nodes.get((ix + dx, iy + dy), []):
                    if oid <= nid:
                        continue
                    nb = graph.nodes[oid]
                    if _dist((na.x_m, na.y_m), (nb.x_m, nb.y_m)) <= epsilon_m:
                        _uf_union(parent, nid, oid)

    clusters: dict[str, list[str]] = {}
    for n in graph.nodes:
        r = _uf_find(parent, n)
        clusters.setdefault(r, []).append(n)
    snap_clusters = 0
    vertices_merged = 0
    for _r, members in clusters.items():
        if len(members) < 2:
            continue
        snap_clusters += 1
        removed = collapse_nodes(graph, sorted(members), merge_kind="snap")
        vertices_merged += removed
    return {
        "epsilon_m": epsilon_m,
        "snap_clusters": snap_clusters,
        "vertices_merged_by_snap": vertices_merged,
    }


def split_one_intersection(graph: RoadGraph, synth_counter: list[int]) -> bool:
    edge_ids_sorted = sorted(graph.edges.keys())
    rank = {eid: i for i, eid in enumerate(edge_ids_sorted)}

    cell_m = _split_grid_cell_m(graph)
    for _ in range(5):
        cell_map = _index_edge_segments_by_cell(graph, cell_m)
        max_occ = max((len(v) for v in cell_map.values()), default=0)
        if max_occ <= _SPLIT_CELL_DENSE_THRESHOLD:
            break
        cell_m *= 0.5

    seen_pairs: set[tuple[str, int, str, int]] = set()
    cand: list[tuple[int, int, int, int, str, str]] = []
    for _cell, refs in cell_map.items():
        loc: set[tuple[str, int]] = set()
        uniq: list[tuple[str, int]] = []
        for r in refs:
            if r in loc:
                continue
            loc.add(r)
            uniq.append(r)
        L = uniq
        for ii in range(len(L)):
            for jj in range(ii + 1, len(L)):
                e1, s1 = L[ii]
                e2, s2 = L[jj]
                if e1 == e2:
                    continue
                if e1 > e2:
                    e1, s1, e2, s2 = e2, s2, e1, s1
                pk = (e1, s1, e2, s2)
                if pk in seen_pairs:
                    continue
                seen_pairs.add(pk)
                cand.append((rank[e1], rank[e2], s1, s2, e1, e2))
    cand.sort()

    for _r1, _r2, seg_i, seg_j, e1_id, e2_id in cand:
        e1 = graph.edges.get(e1_id)
        e2 = graph.edges.get(e2_id)
        if e1 is None or e2 is None:
            continue
        pl1 = e1.polyline_xy_m
        pl2 = e2.polyline_xy_m
        if len(pl1) < 2 or len(pl2) < 2:
            continue
        if seg_i >= len(pl1) - 1 or seg_j >= len(pl2) - 1:
            continue
        a, b = pl1[seg_i], pl1[seg_i + 1]
        c, d = pl2[seg_j], pl2[seg_j + 1]
        pt = segment_intersection_interior(a, b, c, d)
        if pt is None:
            continue
        if _near_any_vertex(pt, pl1) or _near_any_vertex(pt, pl2):
            continue
        _split_edge_at(graph, e1.id, pt, synth_counter)
        _split_edge_at(graph, e2.id, pt, synth_counter)
        return True
    return False


def _near_any_vertex(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    for q in poly:
        if _dist(pt, q) < SEG_PT_TOL_M * 3:
            return True
    return False


def _split_edge_at(
    graph: RoadGraph,
    edge_id: str,
    pt: tuple[float, float],
    synth_counter: list[int],
) -> None:
    e = graph.edges.get(edge_id)
    if e is None:
        return
    pl = e.polyline_xy_m
    if len(pl) < 2:
        del graph.edges[edge_id]
        return
    seg_idx: int | None = None
    best_d = 1e18
    snap_pt = pt
    for i in range(len(pl) - 1):
        proj, _t = nearest_point_on_segment(pt, pl[i], pl[i + 1])
        d = _dist(pt, proj)
        if d < best_d:
            best_d = d
            seg_idx = i
            snap_pt = proj
    if seg_idx is None or best_d > SEG_PT_TOL_M * 10:
        return
    if _dist(snap_pt, pl[seg_idx]) < SEG_PT_TOL_M * 2:
        return
    if _dist(snap_pt, pl[seg_idx + 1]) < SEG_PT_TOL_M * 2:
        return

    synth_counter[0] += 1
    new_nid = f"synth:{synth_counter[0]}"
    graph.nodes[new_nid] = InternalNode(
        id=new_nid,
        x_m=snap_pt[0],
        y_m=snap_pt[1],
        source_osm_node_ids=[],
        is_way_polyline_endpoint=False,
        merged_from_snap=False,
        merged_from_osm_id=False,
    )
    ins_at = seg_idx + 1
    pl_new = list(pl)
    pl_left = pl_new[:ins_at] + [snap_pt]
    pl_right = [snap_pt] + pl_new[ins_at:]
    if len(pl_left) < 2 or len(pl_right) < 2:
        del graph.nodes[new_nid]
        return

    del graph.edges[edge_id]
    u0, v0 = e.u, e.v
    suf = synth_counter[0]
    e_left = f"{edge_id}:L:{suf}"
    e_right = f"{edge_id}:R:{suf}"
    graph.edges[e_left] = InternalEdge(
        id=e_left,
        u=u0,
        v=new_nid,
        polyline_xy_m=_resnap_poly_to_nodes(graph, u0, new_nid, pl_left),
        osm_way_id=e.osm_way_id,
        highway=e.highway,
    )
    graph.edges[e_right] = InternalEdge(
        id=e_right,
        u=new_nid,
        v=v0,
        polyline_xy_m=_resnap_poly_to_nodes(graph, new_nid, v0, pl_right),
        osm_way_id=e.osm_way_id,
        highway=e.highway,
    )


def _resnap_poly_to_nodes(
    graph: RoadGraph,
    u: str,
    v: str,
    pl: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not pl:
        return pl
    nu = graph.nodes[u]
    nv = graph.nodes[v]
    out = list(pl)
    out[0] = (nu.x_m, nu.y_m)
    out[-1] = (nv.x_m, nv.y_m)
    return out


def run_intersection_splits(graph: RoadGraph) -> dict[str, Any]:
    synth_counter = [0]
    splits_applied = 0
    for _ in range(MAX_SPLIT_ITER):
        if not split_one_intersection(graph, synth_counter):
            break
        splits_applied += 1
    return {
        "intersection_splits_applied": splits_applied,
        "new_vertices_from_split": synth_counter[0],
    }


def _incident_edges_by_node(graph: RoadGraph) -> dict[str, list[InternalEdge]]:
    inc: dict[str, list[InternalEdge]] = {nid: [] for nid in graph.nodes}
    for e in graph.edges.values():
        if e.u in inc:
            inc[e.u].append(e)
        if e.v in inc:
            inc[e.v].append(e)
    return inc


def _node_degrees_from_incident(inc: dict[str, list[InternalEdge]]) -> dict[str, int]:
    return {nid: len(lst) for nid, lst in inc.items()}


def classify_vertex_role(
    graph: RoadGraph,
    nid: str,
    deg: dict[str, int],
    incident: dict[str, list[InternalEdge]],
) -> Literal["inline", "junction"]:
    n = graph.nodes[nid]
    synthetic = len(n.source_osm_node_ids) == 0
    d = deg.get(nid, 0)
    if synthetic:
        return "junction"
    if d != 2:
        return "junction"
    if n.is_way_polyline_endpoint:
        return "junction"
    if len(n.source_osm_node_ids) > 1:
        return "junction"
    pair = incident.get(nid)
    if pair is None or len(pair) != 2:
        return "junction"
    e1, e2 = pair[0], pair[1]
    if e1.osm_way_id != e2.osm_way_id:
        return "junction"
    return "inline"


def graph_to_geojson_fc(
    graph: RoadGraph,
    lon0: float,
    lat0: float,
    options: GraphBuildOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    incident = _incident_edges_by_node(graph)
    deg = _node_degrees_from_incident(incident)

    roles: dict[str, str] = {}
    lonlat_by_nid: dict[str, tuple[float, float]] = {}
    for nid in graph.nodes:
        roles[nid] = classify_vertex_role(graph, nid, deg, incident)
        lon, lat = xy_m_to_lon_lat(lon0, lat0, graph.nodes[nid].x_m, graph.nodes[nid].y_m)
        lonlat_by_nid[nid] = (lon, lat)

    pile_key_counts: dict[tuple[float, float], int] = {}
    for lon, lat in lonlat_by_nid.values():
        key = (round(lon, PILE_LONLAT_DECIMALS), round(lat, PILE_LONLAT_DECIMALS))
        pile_key_counts[key] = pile_key_counts.get(key, 0) + 1

    node_feats: list[dict[str, Any]] = []
    for nid, n in graph.nodes.items():
        lon, lat = lonlat_by_nid[nid]
        pk = (round(lon, PILE_LONLAT_DECIMALS), round(lat, PILE_LONLAT_DECIMALS))
        pile_count = pile_key_counts.get(pk, 1)
        synthetic = len(n.source_osm_node_ids) == 0
        role = roles[nid]
        highlight_osm_merge = bool(options.connect_osm_node_ids and n.merged_from_osm_id)
        highlight_snap_merge = bool(options.snap_endpoints and n.merged_from_snap)

        node_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "internal_node_id": nid,
                    "source_osm_node_ids": n.source_osm_node_ids,
                    "synthetic": synthetic,
                    "graph_degree": deg.get(nid, 0),
                    "vertex_role": role,
                    "pile_count": pile_count,
                    "highlight_osm_merge": highlight_osm_merge,
                    "highlight_snap_merge": highlight_snap_merge,
                },
            }
        )

    edge_feats: list[dict[str, Any]] = []
    for eid, e in graph.edges.items():
        coords: list[list[float]] = []
        for p in e.polyline_xy_m:
            llon, llat = xy_m_to_lon_lat(lon0, lat0, p[0], p[1])
            coords.append([llon, llat])
        if len(coords) < 2:
            continue
        edge_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "internal_edge_id": eid,
                    "osm_way_id": e.osm_way_id,
                    "highway": e.highway,
                    "u": e.u,
                    "v": e.v,
                },
            }
        )

    nodes_fc: dict[str, Any] = {"type": "FeatureCollection", "features": node_feats}
    edges_fc: dict[str, Any] = {"type": "FeatureCollection", "features": edge_feats}
    return nodes_fc, edges_fc


def build_graph_from_geojson(
    geojson_fc: dict[str, Any],
    lon0: float,
    lat0: float,
    options: GraphBuildOptions,
) -> GraphBuildResult:
    step_metrics: dict[str, Any] = {}
    ways = parse_way_features(geojson_fc)
    dedupe_rm_edges: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    dedupe_rm_verts: dict[str, Any] = {"type": "FeatureCollection", "features": []}

    if options.deduplicate_geometry:
        dedupe_rm_edges, dedupe_rm_verts = dedupe_removed_geometry_geojson(ways)
        vb = sum(len(w.osm_node_ids) for w in ways)
        ways = dedupe_geometry_ways(ways)
        va = sum(len(w.osm_node_ids) for w in ways)
        step_metrics["deduplicate"] = {
            "way_vertices_before": vb,
            "way_vertices_after": va,
            "removed_duplicate_vertices": vb - va,
        }

    def proj(lon: float, lat: float) -> tuple[float, float]:
        return lon_lat_to_xy_m(lon0, lat0, lon, lat)

    graph = build_native_graph(ways, proj)

    if options.connect_osm_node_ids:
        step_metrics["connect_osm"] = merge_by_osm_node_id(graph)
        step_metrics["connect_osm"]["merged_vertex_count"] = sum(
            1 for n in graph.nodes.values() if n.merged_from_osm_id
        )

    if options.split_intersections:
        step_metrics["split"] = run_intersection_splits(graph)

    if options.snap_endpoints:
        step_metrics["snap"] = snap_endpoints(graph, options.snap_epsilon_m)

    synth = sum(1 for n in graph.nodes.values() if len(n.source_osm_node_ids) == 0)
    stats = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "synthetic_node_count": synth,
        "way_input_count": len(ways),
    }

    return GraphBuildResult(
        graph=graph,
        lon0=lon0,
        lat0=lat0,
        explanation_lines=[],
        stats=stats,
        step_metrics=step_metrics,
        dedupe_removed_edges_geojson=dedupe_rm_edges,
        dedupe_removed_vertices_geojson=dedupe_rm_verts,
    )
