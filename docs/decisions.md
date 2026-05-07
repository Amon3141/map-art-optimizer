# 決定記録

時系列で短く残す。

- **2026-05-06**: 地図ライブラリに **MapLibre GL JS** を採用。OSM 互換ラスタタイルで十分で、後からベクタレイヤを足しやすい。
- **2026-05-06**: Overpass は **FastAPI 経由プロキシ**。CORS とレート配慮のため。
- **2026-05-06**: ストローク簡略化は **自前 Douglas–Peucker**（依存最小）。
- **2026-05-06**: 最適化結果の API 表現は **GeoJSON FeatureCollection** とし、**候補ルート 1 本につき `Feature` を 1 つ**。ジオメトリは WGS84 の `LineString`。`properties` はアルゴリズム結果用（詳細スキーマは未確定）。KML／GPX は **後処理で変換可能**とし、正は GeoJSON に寄せる。
