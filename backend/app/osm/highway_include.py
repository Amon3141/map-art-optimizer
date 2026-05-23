"""本番・デバッグ UI で共通に使う highway=* 値（道路ネットワークに含める種別）。"""

# frontend/src/lib/highwayInclude.ts の INCLUDED_HIGHWAY_TYPES と同期して保つこと。
INCLUDED_HIGHWAY_TYPES: tuple[str, ...] = (
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
)
