import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import type { BasemapMode } from '../components/BasemapSelector'

export const DEFAULT_MAP_CENTER: [number, number] = [139.7671, 35.6812]
export const DEFAULT_MAP_ZOOM = 13

export const BASEMAP_OSM = 'basemap-osm'
export const BASEMAP_LIGHT = 'basemap-light'
export const BASEMAP_DARK = 'basemap-dark'

/** OSM + Carto（ライト／ダーク）を同一スタイルに載せ、visibility で切り替え */
export const BASEMAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
    carto_light: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
    carto_dark: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [
    {
      id: BASEMAP_OSM,
      type: 'raster',
      source: 'osm',
      minzoom: 0,
      maxzoom: 19,
      layout: { visibility: 'visible' },
    },
    {
      id: BASEMAP_LIGHT,
      type: 'raster',
      source: 'carto_light',
      minzoom: 0,
      maxzoom: 20,
      layout: { visibility: 'none' },
    },
    {
      id: BASEMAP_DARK,
      type: 'raster',
      source: 'carto_dark',
      minzoom: 0,
      maxzoom: 20,
      layout: { visibility: 'none' },
    },
  ],
}

export function applyBasemapVisibility(map: MapLibreMap, mode: BasemapMode) {
  for (const id of [BASEMAP_OSM, BASEMAP_LIGHT, BASEMAP_DARK]) {
    if (!map.getLayer(id)) return
  }
  const osmVis = mode === 'normal' ? 'visible' : 'none'
  const lightVis = mode === 'light' ? 'visible' : 'none'
  const darkVis = mode === 'dark' ? 'visible' : 'none'
  map.setLayoutProperty(BASEMAP_OSM, 'visibility', osmVis)
  map.setLayoutProperty(BASEMAP_LIGHT, 'visibility', lightVis)
  map.setLayoutProperty(BASEMAP_DARK, 'visibility', darkVis)
}
