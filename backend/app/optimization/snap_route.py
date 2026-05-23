from __future__ import annotations

import heapq
import math
import time
from typing import TypeAlias

from app.preprocess.graph_model import InternalEdge, RoadGraph
from app.preprocess.helpers import nearest_point_on_segment

from .constants import ROUTE_ARC_SAMPLES
from .types import RouteBuildResult


def _polyline_length_m(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 2:
        return 0.0
    t = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        t += math.hypot(b[0] - a[0], b[1] - a[1])
    return t


def edge_geometric_length_m(e: InternalEdge) -> float:
    return _polyline_length_m(e.polyline_xy_m)


def build_adjacency(graph: RoadGraph) -> dict[str, list[tuple[str, str, float]]]:
    """node_id -> list of (neighbor_id, edge_id, length_m). 重みは幾何長（メートル）。"""
    adj: dict[str, list[tuple[str, str, float]]] = {nid: [] for nid in graph.nodes}
    for eid, e in graph.edges.items():
        w = edge_geometric_length_m(e)
        if e.u in adj:
            adj[e.u].append((e.v, eid, w))
        if e.v in adj:
            adj[e.v].append((e.u, eid, w))
    return adj


def sample_polyline_arc_length(
    pts: list[tuple[float, float]],
    n_samples: int,
) -> list[tuple[float, float]]:
    """弧長等間隔で n 点（端点含む、n>=2）。"""
    if len(pts) < 2 or n_samples < 2:
        return list(pts)
    seg_len: list[float] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg_len.append(math.hypot(b[0] - a[0], b[1] - a[1]))
    total = sum(seg_len)
    if total < 1e-12:
        return [pts[0], pts[-1]]
    out: list[tuple[float, float]] = []
    targets = [j * total / (n_samples - 1) for j in range(n_samples)]
    acc = 0.0
    si = 0
    for tdist in targets:
        while si < len(seg_len) and acc + seg_len[si] < tdist - 1e-9:
            acc += seg_len[si]
            si += 1
        if si >= len(seg_len):
            out.append(pts[-1])
            continue
        a, b = pts[si], pts[si + 1]
        L = seg_len[si]
        local = (tdist - acc) / L if L > 1e-12 else 0.0
        local = max(0.0, min(1.0, local))
        out.append((a[0] + local * (b[0] - a[0]), a[1] + local * (b[1] - a[1])))
    return out


def _segment_nearest_endpoint(
    graph: RoadGraph,
    e: InternalEdge,
    i: int,
    qx: float,
    qy: float,
) -> tuple[str, float]:
    pl = e.polyline_xy_m
    a, b = pl[i], pl[i + 1]
    pt, _t = nearest_point_on_segment((qx, qy), a, b)
    d = math.hypot(pt[0] - qx, pt[1] - qy)
    nu = graph.nodes[e.u]
    nv = graph.nodes[e.v]
    du = math.hypot(nu.x_m - qx, nu.y_m - qy)
    dv = math.hypot(nv.x_m - qx, nv.y_m - qy)
    return (e.u if du <= dv else e.v), d


class EdgeSnapIndexLinear:
    __slots__ = ("graph", "_default_nid")

    def __init__(self, graph: RoadGraph) -> None:
        self.graph = graph
        self._default_nid = next(iter(graph.nodes)) if graph.nodes else ""

    def nearest(self, qx: float, qy: float) -> tuple[str, float]:
        best_seg_d = math.inf
        best_nid = self._default_nid
        for e in self.graph.edges.values():
            pl = e.polyline_xy_m
            if len(pl) < 2:
                continue
            for i in range(len(pl) - 1):
                nid, d = _segment_nearest_endpoint(self.graph, e, i, qx, qy)
                if d < best_seg_d:
                    best_seg_d = d
                    best_nid = nid
        return best_nid, best_seg_d


class EdgeSnapIndexGrid:
    __slots__ = (
        "graph",
        "_default_nid",
        "x0",
        "y0",
        "cw",
        "ch",
        "nx",
        "ny",
        "cells",
        "max_seg_len",
        "cell_min",
    )

    def __init__(
        self,
        graph: RoadGraph,
        x0: float,
        y0: float,
        cw: float,
        ch: float,
        nx: int,
        ny: int,
        cells: list[list[tuple[InternalEdge, int]]],
        max_seg_len: float,
    ) -> None:
        self.graph = graph
        self._default_nid = next(iter(graph.nodes)) if graph.nodes else ""
        self.x0 = x0
        self.y0 = y0
        self.cw = max(cw, 1e-6)
        self.ch = max(ch, 1e-6)
        self.nx = nx
        self.ny = ny
        self.cells = cells
        self.max_seg_len = max_seg_len
        self.cell_min = min(self.cw, self.ch)

    @staticmethod
    def build(graph: RoadGraph) -> EdgeSnapIndexGrid:
        if not graph.nodes:
            return EdgeSnapIndexGrid(graph, 0.0, 0.0, 1.0, 1.0, 1, 1, [[]], 0.0)
        min_x = min(n.x_m for n in graph.nodes.values())
        max_x = max(n.x_m for n in graph.nodes.values())
        min_y = min(n.y_m for n in graph.nodes.values())
        max_y = max(n.y_m for n in graph.nodes.values())
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        margin = max(8.0, 0.02 * max(span_x, span_y))
        x0 = min_x - margin
        y0 = min_y - margin
        span_x += 2.0 * margin
        span_y += 2.0 * margin

        nseg = sum(max(0, len(e.polyline_xy_m) - 1) for e in graph.edges.values())
        target_cell = max(22.0, min(90.0, math.sqrt(span_x * span_y / max(1, nseg / 6.0))))
        nx = min(112, max(10, int(math.ceil(span_x / target_cell))))
        ny = min(112, max(10, int(math.ceil(span_y / target_cell))))
        cw = span_x / nx
        ch = span_y / ny
        cells: list[list[tuple[InternalEdge, int]]] = [[] for _ in range(nx * ny)]
        max_seg_len = 0.0

        for e in graph.edges.values():
            pl = e.polyline_xy_m
            if len(pl) < 2:
                continue
            for i in range(len(pl) - 1):
                ax, ay = pl[i]
                bx, by = pl[i + 1]
                slen = math.hypot(bx - ax, by - ay)
                max_seg_len = max(max_seg_len, slen)
                sminx, smaxx = (min(ax, bx), max(ax, bx))
                sminy, smaxy = (min(ay, by), max(ay, by))
                ix0 = max(0, int((sminx - x0) / cw))
                ix1 = min(nx - 1, int((smaxx - x0) / cw))
                iy0 = max(0, int((sminy - y0) / ch))
                iy1 = min(ny - 1, int((smaxy - y0) / ch))
                for ix in range(ix0, ix1 + 1):
                    for iy in range(iy0, iy1 + 1):
                        cells[ix + iy * nx].append((e, i))

        return EdgeSnapIndexGrid(graph, x0, y0, cw, ch, nx, ny, cells, max_seg_len)

    @staticmethod
    def _iter_chebyshev_ring(ix: int, iy: int, ring: int, nx: int, ny: int):
        """Chebyshev 距離 ring のセルだけ列挙（ring=0 は中心 1 セル）。"""
        if ring == 0:
            if 0 <= ix < nx and 0 <= iy < ny:
                yield ix, iy
            return
        x_lo, x_hi = ix - ring, ix + ring
        y_lo, y_hi = iy - ring, iy + ring
        if 0 <= y_hi < ny:
            cx0 = max(0, x_lo)
            cx1 = min(nx - 1, x_hi)
            for cx in range(cx0, cx1 + 1):
                if max(abs(cx - ix), abs(y_hi - iy)) == ring:
                    yield cx, y_hi
        if y_lo != y_hi and 0 <= y_lo < ny:
            cx0 = max(0, x_lo)
            cx1 = min(nx - 1, x_hi)
            for cx in range(cx0, cx1 + 1):
                if max(abs(cx - ix), abs(y_lo - iy)) == ring:
                    yield cx, y_lo
        for cy in range(max(0, y_lo + 1), min(ny - 1, y_hi - 1) + 1):
            for cx in (x_lo, x_hi):
                if not (0 <= cx < nx):
                    continue
                if max(abs(cx - ix), abs(cy - iy)) == ring:
                    yield cx, cy

    def nearest(self, qx: float, qy: float) -> tuple[str, float]:
        best_seg_d = math.inf
        best_nid = self._default_nid
        ix = int((qx - self.x0) / self.cw)
        iy = int((qy - self.y0) / self.ch)
        ix = max(0, min(self.nx - 1, ix))
        iy = max(0, min(self.ny - 1, iy))
        max_ring = self.nx + self.ny + 2
        seen: set[tuple[int, str, int]] = set()
        for ring in range(0, max_ring + 1):
            # 初めて現れるセグメントは Chebyshev ring >= ring のセルにのみ載る。
            # そのようなセグメントは B_{ring-1} 外に点を持つので、距離は少なくとも (ring-1)*cell_min。
            if ring > 0 and (ring - 1) * self.cell_min > best_seg_d + 1e-9:
                break
            for cx, cy in self._iter_chebyshev_ring(ix, iy, ring, self.nx, self.ny):
                for e, si in self.cells[cx + cy * self.nx]:
                    key = (id(e), e.id, si)
                    if key in seen:
                        continue
                    seen.add(key)
                    nid, d = _segment_nearest_endpoint(self.graph, e, si, qx, qy)
                    if d < best_seg_d:
                        best_seg_d = d
                        best_nid = nid
        if best_seg_d == math.inf:
            return EdgeSnapIndexLinear(self.graph).nearest(qx, qy)
        return best_nid, best_seg_d


AnyEdgeSnapIndex: TypeAlias = EdgeSnapIndexLinear | EdgeSnapIndexGrid


def build_edge_snap_index(graph: RoadGraph) -> AnyEdgeSnapIndex:
    nseg = sum(max(0, len(e.polyline_xy_m) - 1) for e in graph.edges.values())
    if nseg < 160:
        return EdgeSnapIndexLinear(graph)
    return EdgeSnapIndexGrid.build(graph)


class NodeSpatialIndexGrid:
    __slots__ = ("graph", "x0", "y0", "cw", "ch", "nx", "ny", "cells")

    def __init__(
        self,
        graph: RoadGraph,
        x0: float,
        y0: float,
        cw: float,
        ch: float,
        nx: int,
        ny: int,
        cells: list[list[str]],
    ) -> None:
        self.graph = graph
        self.x0 = x0
        self.y0 = y0
        self.cw = max(cw, 1e-6)
        self.ch = max(ch, 1e-6)
        self.nx = nx
        self.ny = ny
        self.cells = cells

    @staticmethod
    def build(graph: RoadGraph) -> NodeSpatialIndexGrid:
        if not graph.nodes:
            return NodeSpatialIndexGrid(graph, 0.0, 0.0, 1.0, 1.0, 1, 1, [[]])
        min_x = min(n.x_m for n in graph.nodes.values())
        max_x = max(n.x_m for n in graph.nodes.values())
        min_y = min(n.y_m for n in graph.nodes.values())
        max_y = max(n.y_m for n in graph.nodes.values())
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        margin = max(8.0, 0.02 * max(span_x, span_y))
        x0 = min_x - margin
        y0 = min_y - margin
        span_x += 2.0 * margin
        span_y += 2.0 * margin
        target_cell = max(25.0, min(120.0, math.sqrt(span_x * span_y / max(1, len(graph.nodes) / 8.0))))
        nx = min(128, max(8, int(math.ceil(span_x / target_cell))))
        ny = min(128, max(8, int(math.ceil(span_y / target_cell))))
        cw = span_x / nx
        ch = span_y / ny
        cells: list[list[str]] = [[] for _ in range(nx * ny)]
        idx = NodeSpatialIndexGrid(graph, x0, y0, cw, ch, nx, ny, cells)
        for nid, node in graph.nodes.items():
            ix = max(0, min(nx - 1, int((node.x_m - x0) / cw)))
            iy = max(0, min(ny - 1, int((node.y_m - y0) / ch)))
            cells[ix + iy * nx].append(nid)
        return idx

    def query_bbox(self, min_x: float, min_y: float, max_x: float, max_y: float) -> list[str]:
        ix0 = max(0, min(self.nx - 1, int((min_x - self.x0) / self.cw)))
        ix1 = max(0, min(self.nx - 1, int((max_x - self.x0) / self.cw)))
        iy0 = max(0, min(self.ny - 1, int((min_y - self.y0) / self.ch)))
        iy1 = max(0, min(self.ny - 1, int((max_y - self.y0) / self.ch)))
        if ix0 > ix1:
            ix0, ix1 = ix1, ix0
        if iy0 > iy1:
            iy0, iy1 = iy1, iy0
        out: list[str] = []
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                out.extend(self.cells[ix + iy * self.nx])
        return out


def build_node_spatial_index(graph: RoadGraph) -> NodeSpatialIndexGrid:
    return NodeSpatialIndexGrid.build(graph)


def nearest_graph_endpoint(
    graph: RoadGraph,
    q: tuple[float, float],
) -> tuple[str, float]:
    """全エッジの折れ線上の最近点を基準に、そのエッジの端点ノードのうち q に近い方を返す（単発用は線形走査）。"""
    return EdgeSnapIndexLinear(graph).nearest(q[0], q[1])


def dijkstra_path(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    source: str,
    target: str,
) -> tuple[list[str], float] | None:
    """無向非負辺重みグラフ上の source–target 最短経路（辺 ID 列と距離）。"""
    if source == target:
        return [], 0.0
    dist: dict[str, float] = {source: 0.0}
    prev: dict[str, tuple[str, str] | None] = {source: None}
    heap: list[tuple[float, str]] = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, math.inf):
            continue
        if u == target:
            break
        for v, eid, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = (u, eid)
                heapq.heappush(heap, (nd, v))
    if target not in dist:
        return None
    edge_ids_rev: list[str] = []
    cur = target
    while cur != source:
        p = prev.get(cur)
        if p is None:
            return None
        pu, pe = p
        edge_ids_rev.append(pe)
        cur = pu
    edge_ids_rev.reverse()
    return edge_ids_rev, dist[target]


def _angle_between_abs(a_rad: float, b_rad: float) -> float:
    diff = (a_rad - b_rad + math.pi) % (2.0 * math.pi) - math.pi
    return abs(diff)


def _node_projection_and_lateral(
    xy: tuple[float, float],
    a: tuple[float, float],
    vx: float,
    vy: float,
    seg_len: float,
) -> tuple[float, float]:
    dx, dy = xy[0] - a[0], xy[1] - a[1]
    along = (dx * vx + dy * vy) / seg_len
    cross = abs(dx * vy - dy * vx) / seg_len
    return along, cross


def _smooth_dp_segment_path(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    start_nid: str,
    end_nid: str,
    source_a: tuple[float, float],
    source_b: tuple[float, float],
    node_index: NodeSpatialIndexGrid | None = None,
) -> list[str] | None:
    """スナップ元の一辺に沿う向き・角度ズレをコストにした DAG DP。失敗時は None。"""
    if start_nid == end_nid:
        return []
    vx = source_b[0] - source_a[0]
    vy = source_b[1] - source_a[1]
    seg_len = math.hypot(vx, vy)
    if seg_len < 1e-9:
        return None

    corridor = max(30.0, min(180.0, 0.25 * seg_len))
    source_angle = math.atan2(vy, vx)
    meta: dict[str, tuple[float, float]] = {}
    if node_index is None:
        candidate_node_ids = list(graph.nodes)
    else:
        min_x = min(source_a[0], source_b[0]) - corridor
        max_x = max(source_a[0], source_b[0]) + corridor
        min_y = min(source_a[1], source_b[1]) - corridor
        max_y = max(source_a[1], source_b[1]) + corridor
        candidate_node_ids = node_index.query_bbox(min_x, min_y, max_x, max_y)
    for nid in candidate_node_ids:
        node = graph.nodes.get(nid)
        if node is None:
            continue
        along, lateral = _node_projection_and_lateral((node.x_m, node.y_m), source_a, vx, vy, seg_len)
        if -corridor <= along <= seg_len + corridor and lateral <= corridor:
            meta[nid] = (along, lateral)
    if start_nid not in meta:
        n = graph.nodes.get(start_nid)
        if n is not None:
            meta[start_nid] = _node_projection_and_lateral((n.x_m, n.y_m), source_a, vx, vy, seg_len)
    if end_nid not in meta:
        n = graph.nodes.get(end_nid)
        if n is not None:
            meta[end_nid] = _node_projection_and_lateral((n.x_m, n.y_m), source_a, vx, vy, seg_len)
    if start_nid not in meta or end_nid not in meta:
        return None

    ordered = sorted(meta, key=lambda nid: (meta[nid][0], meta[nid][1]))
    dist: dict[str, float] = {start_nid: 0.0}
    prev: dict[str, tuple[str, str] | None] = {start_nid: None}
    eps = max(1e-6, seg_len * 1e-6)

    for u in ordered:
        if u not in dist:
            continue
        u_along, _ = meta[u]
        for v, eid, length_m in adj.get(u, []):
            if v not in meta:
                continue
            v_along, v_lateral = meta[v]
            if v_along <= u_along + eps:
                continue
            e = graph.edges.get(eid)
            if e is None or len(e.polyline_xy_m) < 2:
                continue
            ux, uy = graph.nodes[u].x_m, graph.nodes[u].y_m
            vx_node, vy_node = graph.nodes[v].x_m, graph.nodes[v].y_m
            edge_angle = math.atan2(vy_node - uy, vx_node - ux)
            angle_cost = _angle_between_abs(edge_angle, source_angle) / math.pi
            lateral_cost = v_lateral / max(corridor, 1.0)
            length_cost = length_m / max(seg_len, 1.0)
            nd = dist[u] + angle_cost * length_cost + 0.05 * lateral_cost + 0.001 * length_cost
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = (u, eid)

    if end_nid not in prev:
        return None
    edge_ids_rev: list[str] = []
    cur = end_nid
    while cur != start_nid:
        p = prev.get(cur)
        if p is None:
            return None
        pu, pe = p
        edge_ids_rev.append(pe)
        cur = pu
    edge_ids_rev.reverse()
    return edge_ids_rev


def concatenate_edge_polylines(
    graph: RoadGraph,
    edge_ids: list[str],
) -> list[tuple[float, float]]:
    """エッジ列を向きに沿って連結した折れ線（重複頂点は間引き）。"""
    if not edge_ids:
        return []
    out: list[tuple[float, float]] = []
    last_xy: tuple[float, float] | None = None

    for eid in edge_ids:
        e = graph.edges.get(eid)
        if e is None:
            continue
        pl = list(e.polyline_xy_m)
        if len(pl) < 2:
            continue
        if last_xy is not None:
            d0 = math.hypot(pl[0][0] - last_xy[0], pl[0][1] - last_xy[1])
            d1 = math.hypot(pl[-1][0] - last_xy[0], pl[-1][1] - last_xy[1])
            if d1 < d0:
                pl = list(reversed(pl))
        if out and pl:
            if math.hypot(pl[0][0] - out[-1][0], pl[0][1] - out[-1][1]) < 1e-6:
                pl = pl[1:]
        out.extend(pl)
        last_xy = out[-1] if out else None

    return out


def _build_nearest_sample_route(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    polyline_xy_m: list[tuple[float, float]],
    arc_samples: int = ROUTE_ARC_SAMPLES,
    snap_index: AnyEdgeSnapIndex | None = None,
) -> RouteBuildResult:
    if len(polyline_xy_m) < 2:
        return RouteBuildResult([], [], False, 0)

    snap = snap_index or build_edge_snap_index(graph)
    samples = sample_polyline_arc_length(polyline_xy_m, arc_samples)
    snap_nodes: list[str] = []
    for s in samples:
        nid, _d = snap.nearest(s[0], s[1])
        snap_nodes.append(nid)

    all_edges: list[str] = []
    failures = 0
    for i in range(len(snap_nodes) - 1):
        a, b = snap_nodes[i], snap_nodes[i + 1]
        if a == b:
            continue
        res = dijkstra_path(graph, adj, a, b)
        if res is None:
            failures += 1
            continue
        seg_edges, _ = res
        for eid in seg_edges:
            if all_edges and all_edges[-1] == eid:
                continue
            all_edges.append(eid)

    route_line = concatenate_edge_polylines(graph, all_edges)
    reachable = failures == 0 and len(all_edges) > 0
    return RouteBuildResult(all_edges, route_line, reachable, failures)


def _build_smooth_dp_route(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    polyline_xy_m: list[tuple[float, float]],
    snap_index: AnyEdgeSnapIndex | None = None,
    node_index: NodeSpatialIndexGrid | None = None,
    deadline: float | None = None,
) -> RouteBuildResult:
    if len(polyline_xy_m) < 2:
        return RouteBuildResult([], [], False, 0)
    snap = snap_index or build_edge_snap_index(graph)
    all_edges: list[str] = []
    failures = 0

    for i in range(len(polyline_xy_m) - 1):
        if deadline is not None and time.monotonic() >= deadline:
            break
        a_xy, b_xy = polyline_xy_m[i], polyline_xy_m[i + 1]
        if math.hypot(b_xy[0] - a_xy[0], b_xy[1] - a_xy[1]) < 1e-9:
            continue
        start_nid, _ = snap.nearest(a_xy[0], a_xy[1])
        end_nid, _ = snap.nearest(b_xy[0], b_xy[1])
        seg_edges = _smooth_dp_segment_path(graph, adj, start_nid, end_nid, a_xy, b_xy, node_index)
        if seg_edges is None:
            fallback = dijkstra_path(graph, adj, start_nid, end_nid)
            if fallback is None:
                failures += 1
                continue
            seg_edges, _ = fallback
        for eid in seg_edges:
            if all_edges and all_edges[-1] == eid:
                continue
            all_edges.append(eid)

    route_line = concatenate_edge_polylines(graph, all_edges)
    reachable = failures == 0 and len(all_edges) > 0
    return RouteBuildResult(all_edges, route_line, reachable, failures)


def build_route_from_polyline(
    graph: RoadGraph,
    adj: dict[str, list[tuple[str, str, float]]],
    polyline_xy_m: list[tuple[float, float]],
    arc_samples: int = ROUTE_ARC_SAMPLES,
    snap_index: AnyEdgeSnapIndex | None = None,
    node_index: NodeSpatialIndexGrid | None = None,
    snap_strategy: str = "smooth_dp",
    deadline: float | None = None,
) -> RouteBuildResult:
    if snap_strategy == "nearest":
        return _build_nearest_sample_route(graph, adj, polyline_xy_m, arc_samples, snap_index)
    return _build_smooth_dp_route(graph, adj, polyline_xy_m, snap_index, node_index, deadline=deadline)
