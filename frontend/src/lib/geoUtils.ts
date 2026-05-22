/** 地図表示用の GeoJSON ジオメトリ生成ユーティリティ */

/**
 * 指定した中心・半径の円を近似する GeoJSON Polygon Feature を返す。
 * 平面近似（緯度方向と経度方向で別々に度換算）を使用。
 */
export function circlePolygon(
  lon: number,
  lat: number,
  radiusM: number,
  n = 64,
): GeoJSON.Feature<GeoJSON.Polygon> {
  const dLat = radiusM / 111_320
  const dLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180))
  const coords: [number, number][] = []
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI
    coords.push([lon + dLon * Math.sin(a), lat + dLat * Math.cos(a)])
  }
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [coords] },
  }
}
