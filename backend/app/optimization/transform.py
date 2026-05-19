from __future__ import annotations

import math

from app.preprocess.graph_model import RoadGraph

from .types import StrokePoint, Transform


def graph_xy_bounds(graph: RoadGraph) -> tuple[float, float, float, float]:
    if not graph.nodes:
        return 0.0, 0.0, 1.0, 1.0
    xs = [n.x_m for n in graph.nodes.values()]
    ys = [n.y_m for n in graph.nodes.values()]
    return min(xs), min(ys), max(xs), max(ys)


def stroke_to_base_polyline_m(
    stroke: list[StrokePoint],
    graph: RoadGraph,
    margin_ratio: float = 0.06,
) -> list[tuple[float, float]]:
    """キャンバス座標のストロークを、ノード外接矩形内（余白付き）に等比フィットした平面折れ線に変換。"""
    if len(stroke) < 2:
        return []

    min_x = min(p.x for p in stroke)
    min_y = min(p.y for p in stroke)
    max_x = max(p.x for p in stroke)
    max_y = max(p.y for p in stroke)
    bw = max(max_x - min_x, 1e-9)
    bh = max(max_y - min_y, 1e-9)

    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    gw = max(gx1 - gx0, 1.0)
    gh = max(gy1 - gy0, 1.0)
    cx = (gx0 + gx1) / 2.0
    cy = (gy0 + gy1) / 2.0
    m = margin_ratio
    uw = gw * (1.0 - 2.0 * m)
    uh = gh * (1.0 - 2.0 * m)
    s = min(uw / bw, uh / bh)

    out: list[tuple[float, float]] = []
    for p in stroke:
        # Canvas は y-down、局所平面座標は y-up なので y だけ反転する。
        qx = (p.x - (min_x + max_x) / 2.0) * s
        qy = -(p.y - (min_y + max_y) / 2.0) * s
        out.append((cx + qx, cy + qy))
    return out


def strokes_to_base_polylines_m_shared(
    components: list[list[StrokePoint]],
    graph: RoadGraph,
    margin_ratio: float = 0.06,
) -> list[list[tuple[float, float]]]:
    """全コンポーネント合算の bounding box から共通スケールを計算し、相対位置を保ったまま各 base polyline を返す。"""
    all_points = [p for comp in components for p in comp]
    if not all_points:
        return [[] for _ in components]

    min_x = min(p.x for p in all_points)
    min_y = min(p.y for p in all_points)
    max_x = max(p.x for p in all_points)
    max_y = max(p.y for p in all_points)
    bw = max(max_x - min_x, 1e-9)
    bh = max(max_y - min_y, 1e-9)
    cx_canvas = (min_x + max_x) / 2.0
    cy_canvas = (min_y + max_y) / 2.0

    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    gw = max(gx1 - gx0, 1.0)
    gh = max(gy1 - gy0, 1.0)
    cx = (gx0 + gx1) / 2.0
    cy = (gy0 + gy1) / 2.0
    m = margin_ratio
    uw = gw * (1.0 - 2.0 * m)
    uh = gh * (1.0 - 2.0 * m)
    s = min(uw / bw, uh / bh)

    result: list[list[tuple[float, float]]] = []
    for comp in components:
        poly: list[tuple[float, float]] = []
        for p in comp:
            qx = (p.x - cx_canvas) * s
            qy = -(p.y - cy_canvas) * s  # canvas y-down → local plane y-up
            poly.append((cx + qx, cy + qy))
        result.append(poly)
    return result


def apply_transform(
    base_xy_m: list[tuple[float, float]],
    transform: Transform,
    center_xy: tuple[float, float],
) -> list[tuple[float, float]]:
    cx, cy = center_xy
    co = math.cos(transform.theta_rad)
    si = math.sin(transform.theta_rad)
    sc = transform.scale
    out: list[tuple[float, float]] = []
    for x, y in base_xy_m:
        dx = x - cx
        dy = y - cy
        rx = sc * (co * dx - si * dy)
        ry = sc * (si * dx + co * dy)
        out.append((rx + cx + transform.tx_m, ry + cy + transform.ty_m))
    return out


def graph_center_m(graph: RoadGraph) -> tuple[float, float]:
    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    return (gx0 + gx1) / 2.0, (gy0 + gy1) / 2.0


def graph_bbox_diagonal_m(graph: RoadGraph) -> float:
    gx0, gy0, gx1, gy1 = graph_xy_bounds(graph)
    return max(1.0, math.hypot(gx1 - gx0, gy1 - gy0))
