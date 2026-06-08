# 道路グラフ

OSM の highway way を平面 `RoadGraph` に変換し、スナップとルーティングに使う。

## OSM 取得

本番（`backend/app/routes.py` の `POST /api/optimize`）:

1. 地図中心 + `fetch_radius_m`（1,000〜5,000 m、既定 2,000 m）から bbox を計算
2. Overpass で以下の `highway` 値を持つ way を取得（`backend/app/osm/highway_include.py`）:

   `trunk`, `primary`, `secondary`, `tertiary`, `unclassified`, `residential`, `service`

3. way 数が `OVERPASS_MAX_WAYS`（`backend/app/preprocess/defaults.py`）を超える場合、OSM way ID 昇順で先頭 N 件のみ使用（エラーにしない）
4. ネイティブノード数が `MAX_NATIVE_GRAPH_NODES`（35,000、`backend/app/optimization/app_defaults.py`）を超える場合、HTTP 400 `graph_too_many_nodes`

motorway は GPS アートに不向き、footway は件数が多く車道と並行しがちなため除外している。

## 投影

WGS84 を取得原点中心の局所接平面へ投影（`backend/app/osm/projection.py`）:

```
x = R · cos(lat0) · Δlon
y = R · Δlat
```

距離・スナップ・スコア計算はすべてこの平面メートル座標で行う。

## 取り込み

`backend/app/osm/ingest.py` が LineString の GeoJSON FeatureCollection を `RoadGraph` に変換する:

- 平面座標を持つ頂点
- 長さ、`highway` タグ、OSM way メタデータ、任意の polyline ジオメトリを持つ辺

## 前処理パイプライン

`backend/app/preprocess/pipeline.py` の `preprocess_road_graph` が以下の順でオプションを適用する:

| ステップ | オプションフラグ | 本番既定 |
|---------|-----------------|---------|
| 同一 OSM node ID の頂点をマージ | `connect_osm_node_ids_enabled` | ON |
| 近接端点の ε スナップ | `snap_endpoints_enabled` | OFF |
| 並行・重複道路のマージ | `merge_duplicate_roads_enabled` | ON |
| 幾何交差での辺分割 | `split_intersections_enabled` | OFF |
| 次数 2 チェーン頂点の削減 | `remove_redundant_chain_vertices_enabled` | ON |

本番は `backend/app/preprocess/defaults.py` の既定（connect + merge + prune のみ）を使用。

### 端点スナップ

有効時（`backend/app/preprocess/options/snap_endpoints.py`）: STRtree で ε 以内の頂点ペアを列挙。少なくとも一方が way 端点かつ同一辺の両端でない場合のみマージ。

### 交差 split

有効時（`backend/app/preprocess/options/split_intersections.py`）: STRtree でセグメント bbox の重なり候補を列挙。内部交点で辺を分割し、交差道路をグラフノード化。

### 重複道路マージ

有効時（`backend/app/preprocess/options/merge_duplicate_roads.py`）: STRtree で並行重なりセグメントを列挙。union-find でグループ化し、代表コリドー辺へ畳み込む。

### チェーン prune

有効時（`backend/app/preprocess/options/prune_chains.py`）: 同一 OSM way 上の次数 2 頂点を、意味のある曲率を表す場合を除いて削除。符号付き累積折れ角（既定閾値 ~10°）で緩いカーブは残し、ノイズ的なジグザグを潰す。

## 空間索引

スナップ・split・マージは Shapely STRtree で候補を絞る。最適化のスナップ処理はグラフ辺用の空間索引を別途構築する。

## グラフ出力

前処理後、`graph_to_geojson_fc` が node/edge の FeatureCollection を生成する（デバッグ可視化・内部利用）。最適化パイプラインはメモリ上の `RoadGraph` を受け取る。

## 関連ドキュメント

- [アーキテクチャ](architecture.md)
- [最適化](optimization.md)
- [開発](development.md) — デバッグ UI で前処理オプションを切り替え可能
