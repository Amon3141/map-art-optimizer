"""Prune redundant degree-2 chain vertices on a single OSM way."""

from __future__ import annotations

import math
from typing import Any

from .helpers import (
    _incident_edges_by_node,
    _merge_edge_osm_way_ids,
    _node_degrees_from_incident,
)
from ..graph_model import InternalEdge, RoadGraph

DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG = 15.0

_PRUNE_LEN_EPS_SQ = 1e-18


def _other_vertex(e: InternalEdge, nid: str) -> str:
    return e.v if e.u == nid else e.u


class _UndirectedEdgeIndex:
    """無向 {u,v} キーごとの辺 id 一覧。チェーン簡略化での全辺スキャンを避ける。"""

    def __init__(self, graph: RoadGraph):
        self.g = graph
        self.uv_eids: dict[tuple[str, str], list[str]] = {}
        for eid, e in graph.edges.items():
            self._register_edge_id(eid, e)

    @staticmethod
    def uv_key(u: str, v: str) -> tuple[str, str]:
        return (u, v) if u < v else (v, u)

    def _register_edge_id(self, eid: str, e: InternalEdge) -> None:
        k = self.uv_key(e.u, e.v)
        self.uv_eids.setdefault(k, []).append(eid)

    def unregister_edge(self, e: InternalEdge, eid: str) -> None:
        k = self.uv_key(e.u, e.v)
        lst = self.uv_eids.get(k)
        if not lst:
            return
        for idx, x in enumerate(lst):
            if x == eid:
                lst[idx] = lst[-1]
                lst.pop()
                break
        if not lst:
            del self.uv_eids[k]

    def register_new_edge(self, eid: str, e: InternalEdge) -> None:
        self._register_edge_id(eid, e)

    def edges_between(self, u: str, v: str) -> list[InternalEdge]:
        k = self.uv_key(u, v)
        out: list[InternalEdge] = []
        for eid in self.uv_eids.get(k, ()):
            e = self.g.edges.get(eid)
            if e is None:
                continue
            if self.uv_key(e.u, e.v) != k:
                continue
            out.append(e)
        return out


def _prune_vertex_eligible(d: int, es: list[InternalEdge]) -> bool:
    if d != 2:
        return False
    if len(es) != 2:
        return False
    w1, w2 = es[0].osm_way_id, es[1].osm_way_id
    return w1 is not None and w1 == w2


def _signed_turn_at_vertex_rad(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> float:
    """符号付き折れ角（進行方向 P[i-1]→P[i]→P[i+1]）。退化時は 0。"""
    ux, uy = bx - ax, by - ay
    vx, vy = cx - bx, cy - by
    cu = ux * ux + uy * uy
    cv = vx * vx + vy * vy
    if cu < _PRUNE_LEN_EPS_SQ or cv < _PRUNE_LEN_EPS_SQ:
        return 0.0
    return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)


def _prune_accum_reduce_signed_mod(accum: float, threshold_rad: float) -> float:
    """|accum| から threshold の整数倍を符号方向に沿って差し引く（累積のモジュロ）。"""
    if abs(accum) < threshold_rad - 1e-15:
        return accum
    q = math.floor(abs(accum) / threshold_rad + 1e-12)
    return accum - math.copysign(q * threshold_rad, accum)


def _prune_bfs_component(
    start: str,
    eligible: dict[str, bool],
    inc: dict[str, list[InternalEdge]],
) -> set[str]:
    from collections import deque

    comp: set[str] = set()
    dq = deque([start])
    comp.add(start)
    while dq:
        cur = dq.popleft()
        for e in inc[cur]:
            o = _other_vertex(e, cur)
            if eligible.get(o) and o not in comp:
                comp.add(o)
                dq.append(o)
    return comp


def _prune_chain_ordered_endpoints(
    comp: set[str],
    inc: dict[str, list[InternalEdge]],
    eligible: dict[str, bool],
) -> list[str] | None:
    """[frozen_a, …prunable…, frozen_b] or None (pure prunable cycle — skip)."""

    def pr_nbrs(nid: str) -> list[str]:
        return [_other_vertex(e, nid) for e in inc[nid] if eligible.get(_other_vertex(e, nid), False)]

    endpoints = [nid for nid in comp if len(pr_nbrs(nid)) == 1]

    if len(comp) == 1:
        v = next(iter(comp))
        frozen = sorted(
            (_other_vertex(e, v) for e in inc[v] if not eligible.get(_other_vertex(e, v), False)),
            key=str,
        )
        if len(frozen) != 2:
            return None
        return [frozen[0], v, frozen[1]]

    if not endpoints:
        return None

    e0 = min(endpoints, key=str)
    nbr_all = [_other_vertex(e, e0) for e in inc[e0]]
    frozen_start = sorted(
        (x for x in nbr_all if not eligible.get(x, False)),
        key=str,
    )
    if not frozen_start:
        return None
    f0 = frozen_start[0]
    pr_next = [x for x in nbr_all if eligible.get(x, False)]
    if len(pr_next) != 1:
        return None

    order: list[str] = [f0, e0]
    prev, cur = f0, e0
    while True:
        nxt_cand = [_other_vertex(e, cur) for e in inc[cur] if _other_vertex(e, cur) != prev]
        if len(nxt_cand) != 1:
            return None
        nxt = nxt_cand[0]
        if not eligible.get(nxt, False):
            order.append(nxt)
            return order
        order.append(nxt)
        prev, cur = cur, nxt


def _prune_simplify_keep_indices(
    order: list[str],
    graph: RoadGraph,
    eligible: dict[str, bool],
    threshold_rad: float,
) -> list[int]:
    """元ポリライン上の符号付き折れ角を累積し、|累積| が閾値を超えた頂点を残す（1 パス）。"""
    n = len(order)
    if n < 2:
        return [0] if n else []
    if n == 2:
        return [0, 1]

    def xy(nid: str) -> tuple[float, float]:
        node = graph.nodes[nid]
        return (node.x_m, node.y_m)

    keep_ix: list[int] = [0]
    accum = 0.0
    last_i = n - 1
    for i in range(1, last_i):
        if not eligible.get(order[i], False):
            if keep_ix[-1] != i:
                keep_ix.append(i)
            accum = 0.0
            continue
        ax, ay = xy(order[i - 1])
        bx, by = xy(order[i])
        cx, cy = xy(order[i + 1])
        accum += _signed_turn_at_vertex_rad(ax, ay, bx, by, cx, cy)
        if abs(accum) >= threshold_rad - 1e-15:
            if keep_ix[-1] != i:
                keep_ix.append(i)
            accum = _prune_accum_reduce_signed_mod(accum, threshold_rad)
    if keep_ix[-1] != last_i:
        keep_ix.append(last_i)
    return keep_ix


def _prune_apply_order(
    graph: RoadGraph,
    order: list[str],
    keep_ix: list[int],
    eligible: dict[str, bool],
    eid_counter: list[int],
    uv_index: _UndirectedEdgeIndex,
) -> int:
    """Returns number of prunable vertices removed."""
    keep_ids = {order[i] for i in keep_ix}
    removed = 0
    for k in range(len(keep_ix) - 1):
        lo, hi = keep_ix[k], keep_ix[k + 1]
        if hi - lo < 2:
            continue
        u0, v0 = order[lo], order[hi]
        edges_del: list[str] = []
        collapse_edges: list[InternalEdge] = []
        wid: int | None = None
        hw: str | None = None
        for t in range(lo, hi):
            a, b = order[t], order[t + 1]
            segment_edges = uv_index.edges_between(a, b)
            if not segment_edges:
                return removed
            for e in segment_edges:
                edges_del.append(e.id)
                collapse_edges.append(e)
                if wid is None:
                    wid = e.osm_way_id
                    hw = e.highway
        nu = graph.nodes[u0]
        nv = graph.nodes[v0]
        # 潰した区間は幾何的にほぼ一直線なので、表示・トポロジは端点間の 2 点折れ線に統一する
        pl = [(nu.x_m, nu.y_m), (nv.x_m, nv.y_m)]
        for eid in edges_del:
            e_old = graph.edges.pop(eid, None)
            if e_old is not None:
                uv_index.unregister_edge(e_old, eid)
        eid_counter[0] += 1
        new_id = f"prune:{eid_counter[0]}:{u0}:{v0}"
        new_e = InternalEdge(
            id=new_id,
            u=u0,
            v=v0,
            polyline_xy_m=pl,
            osm_way_id=wid,
            highway=hw,
            merged_osm_way_ids=_merge_edge_osm_way_ids(collapse_edges),
        )
        graph.edges[new_id] = new_e
        uv_index.register_new_edge(new_id, new_e)

    for nid in order:
        if eligible.get(nid, False) and nid not in keep_ids and nid in graph.nodes:
            del graph.nodes[nid]
            removed += 1
    return removed


def _prune_remove_edges_with_missing_endpoints(
    graph: RoadGraph, uv_index: _UndirectedEdgeIndex | None = None
) -> int:
    """削除済み頂点を参照している辺を除去。削除した本数を返す。"""
    bad = [eid for eid, e in graph.edges.items() if e.u not in graph.nodes or e.v not in graph.nodes]
    for eid in bad:
        e = graph.edges.get(eid)
        if e is not None and uv_index is not None:
            uv_index.unregister_edge(e, eid)
        graph.edges.pop(eid, None)
    return len(bad)


def prune_redundant_chain_vertices(
    graph: RoadGraph,
    accum_threshold_deg: float = DEFAULT_PRUNE_CHAIN_ACCUM_ANGLE_DEG,
) -> dict[str, Any]:
    """同一 way 上の次数 2 の頂点を、ノード種別に関わらず符号付き折れ角の累積に基づき簡略化してマージする。"""
    threshold_rad = math.radians(accum_threshold_deg)
    vertices_removed = 0
    eid_counter = [0]
    blocked: set[str] = set()
    uv_index = _UndirectedEdgeIndex(graph)

    while True:
        inc = _incident_edges_by_node(graph)
        deg = _node_degrees_from_incident(inc)
        eligible: dict[str, bool] = {}
        for nid in graph.nodes:
            if nid in blocked:
                eligible[nid] = False
                continue
            eligible[nid] = _prune_vertex_eligible(deg.get(nid, 0), inc.get(nid, []))

        start = next((nid for nid, ok in eligible.items() if ok), None)
        if start is None:
            break

        comp = _prune_bfs_component(start, eligible, inc)
        order = _prune_chain_ordered_endpoints(comp, inc, eligible)
        if order is None or len(order) < 3:
            blocked |= comp
            continue

        keep_ix = _prune_simplify_keep_indices(order, graph, eligible, threshold_rad)
        any_merge = any(keep_ix[k + 1] - keep_ix[k] >= 2 for k in range(len(keep_ix) - 1))
        if not any_merge:
            blocked |= comp
            continue

        vertices_removed += _prune_apply_order(graph, order, keep_ix, eligible, eid_counter, uv_index)
        _prune_remove_edges_with_missing_endpoints(graph, uv_index)

    _prune_remove_edges_with_missing_endpoints(graph, uv_index)

    th_deg = round(accum_threshold_deg, 9)
    return {
        "vertices_removed": vertices_removed,
        "angle_accum_threshold_deg": th_deg,
    }

