"""前処理の複数モジュールで共有する補助関数（ステップ横断）。"""

from __future__ import annotations

import math

from .graph_model import InternalEdge, RoadGraph


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


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


def _edge_way_ids(e: InternalEdge) -> list[int]:
    ids = list(e.merged_osm_way_ids)
    if e.osm_way_id is not None:
        ids.append(e.osm_way_id)
    return sorted(set(ids))


def _merge_edge_osm_way_ids(edges: list[InternalEdge]) -> list[int]:
    out: set[int] = set()
    for e in edges:
        out.update(_edge_way_ids(e))
    return sorted(out)


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
