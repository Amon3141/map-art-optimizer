"""Epsilon snap of way polyline endpoints."""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import Point

from .helpers import _dist
from ..graph_model import InternalEdge, InternalNode, RoadGraph

from .connect_osm import _merge_source_ids, _uf_find, _uf_union


def snap_endpoints(graph: RoadGraph, epsilon_m: float) -> dict[str, Any]:
    """ε 近傍の頂点を union（条件付き）。

    - 同一グラフ辺の両端どうしは結合しない（polyline 上の隣接頂点同士を除外）。
    - どちらも OSM 折れ線の端点でない頂点同士は結合しない。
    """
    eps = max(epsilon_m, 1e-6)
    nids = list(graph.nodes.keys())
    pts = [Point(graph.nodes[i].x_m, graph.nodes[i].y_m) for i in nids]
    tree = STRtree(pts)

    direct_edge_pairs: set[tuple[str, str]] = set()
    for e in graph.edges.values():
        a, b = e.u, e.v
        if a > b:
            a, b = b, a
        direct_edge_pairs.add((a, b))

    parent = {n: n for n in graph.nodes}
    for nid in nids:
        na = graph.nodes[nid]
        q = Point(na.x_m, na.y_m)
        hits = tree.query(q, predicate="dwithin", distance=eps)
        for hj in np.atleast_1d(np.asarray(hits)):
            j = int(hj)
            oid = nids[j]
            if oid <= nid:
                continue
            nb = graph.nodes[oid]
            pu = (nid, oid) if nid < oid else (oid, nid)
            if pu in direct_edge_pairs:
                continue
            if not (na.is_way_polyline_endpoint or nb.is_way_polyline_endpoint):
                continue
            if _dist((na.x_m, na.y_m), (nb.x_m, nb.y_m)) <= epsilon_m:
                _uf_union(parent, nid, oid)

    clusters: dict[str, list[str]] = {}
    for n in graph.nodes:
        r = _uf_find(parent, n)
        clusters.setdefault(r, []).append(n)

    rem: dict[str, str] = {}
    merged_canonical: dict[str, InternalNode] = {}
    snap_clusters = 0
    vertices_merged = 0
    for _root, members in clusters.items():
        canonical = min(members)
        for k in members:
            rem[k] = canonical
        if len(members) < 2:
            continue
        snap_clusters += 1
        vertices_merged += len(members) - 1
        xs = sum(graph.nodes[k].x_m for k in members) / len(members)
        ys = sum(graph.nodes[k].y_m for k in members) / len(members)
        src = _merge_source_ids([graph.nodes[k].source_osm_node_ids for k in members])
        ep_any = any(graph.nodes[k].is_way_polyline_endpoint for k in members)
        osm_merge_any = any(graph.nodes[k].merged_from_osm_id for k in members)
        merged_canonical[canonical] = InternalNode(
            id=canonical,
            x_m=xs,
            y_m=ys,
            source_osm_node_ids=src,
            is_way_polyline_endpoint=ep_any,
            merged_from_snap=True,
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
            merged_osm_way_ids=list(e.merged_osm_way_ids),
        )
    graph.nodes = final_nodes
    graph.edges = new_edges
    return {
        "epsilon_m": epsilon_m,
        "snap_clusters": snap_clusters,
        "vertices_merged_by_snap": vertices_merged,
    }
