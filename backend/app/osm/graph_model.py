"""Mutable road graph in projected meters (debug / preprocessing intermediate)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InternalNode:
    id: str
    x_m: float
    y_m: float
    source_osm_node_ids: list[int] = field(default_factory=list)
    """OSM の折れ線としての端点（way の先頭／末尾頂点）。マージ時は論理和。"""
    is_way_polyline_endpoint: bool = False
    """距離 snap で複数頂点がまとめられた代表頂点（可視化・メトリクス用）。"""
    merged_from_snap: bool = False
    """同一 OSM node id の複数グラフ頂点をマージした代表頂点。"""
    merged_from_osm_id: bool = False


@dataclass
class InternalEdge:
    id: str
    u: str
    v: str
    polyline_xy_m: list[tuple[float, float]]
    osm_way_id: int | None
    highway: str | None


@dataclass
class RoadGraph:
    nodes: dict[str, InternalNode]
    edges: dict[str, InternalEdge]
