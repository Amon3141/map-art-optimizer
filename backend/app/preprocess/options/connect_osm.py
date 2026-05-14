"""同一 OSM node id を共有するグラフ頂点をマージする。"""

from __future__ import annotations

from typing import Any

from ..graph_model import InternalEdge, InternalNode, RoadGraph

def _merge_source_ids(lists: list[list[int]]) -> list[int]:
    s: set[int] = set()
    for lst in lists:
        for x in lst:
            s.add(x)
    return sorted(s)


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
            merged_osm_way_ids=list(e.merged_osm_way_ids),
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
