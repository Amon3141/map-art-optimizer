import json
from typing import Any


def way_element_for_preview(el: dict[str, Any]) -> dict[str, Any]:
    """テキストプレビュー用: タグ等はそのまま、nodes / geometry は件数のみ。"""
    nodes = el.get("nodes")
    geometry = el.get("geometry")
    preview = {k: v for k, v in el.items() if k not in ("nodes", "geometry")}
    preview["nodes_count"] = len(nodes) if isinstance(nodes, list) else 0
    preview["geometry_count"] = len(geometry) if isinstance(geometry, list) else 0
    return preview


def ways_raw_preview(ways: list[dict[str, Any]], *, max_chars: int = 12000) -> str:
    preview_obj: dict[str, Any] = {
        "elements": [way_element_for_preview(w) for w in ways],
    }
    raw_preview = json.dumps(preview_obj, ensure_ascii=False, indent=2)
    if len(raw_preview) > max_chars:
        return raw_preview[:max_chars] + "\n… (truncated)"
    return raw_preview
