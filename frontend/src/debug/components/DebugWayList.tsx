import { useEffect, useRef } from 'react'

export function wayIdFromProps(props: GeoJSON.GeoJsonProperties): number | string | null {
  if (!props || typeof props !== 'object') return null
  const raw = (props as Record<string, unknown>).osm_way_id
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.length > 0) return raw
  return null
}

function tagValueString(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return JSON.stringify(v)
}

/** OSM 由来の properties を `key: value` の行に並べる（osm_way_id / id を先頭に） */
function sortedTagLines(props: Record<string, unknown>): [string, string][] {
  const pairs = Object.entries(props).filter(([, v]) => v !== undefined)
  pairs.sort(([a], [b]) => {
    if (a === 'osm_way_id') return -1
    if (b === 'osm_way_id') return 1
    if (a === 'id') return -1
    if (b === 'id') return 1
    return a.localeCompare(b, 'ja')
  })
  return pairs.map(([k, v]) => [k, tagValueString(v)])
}

export type DebugWayListProps = {
  features: GeoJSON.Feature[]
  selectedWayId: number | string | null
  onSelectWay: (id: number | string | null) => void
}

export function DebugWayList({ features, selectedWayId, onSelectWay }: DebugWayListProps) {
  const cardRefs = useRef(new Map<string, HTMLElement>())

  useEffect(() => {
    if (selectedWayId == null) return
    const el = cardRefs.current.get(String(selectedWayId))
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedWayId])

  if (features.length === 0) {
    return <p className="px-3 py-6 text-center text-sm text-stone-500">（道路データなし）</p>
  }

  return (
    <ul className="flex flex-col gap-2.5 p-2">
      {features
        .map((f) => {
          if (f.geometry.type !== 'LineString') return null
          const id = wayIdFromProps(f.properties)
          if (id == null) return null
          const p = (f.properties || {}) as Record<string, unknown>
          const nameTag = typeof p.name === 'string' ? p.name : null
          const title = nameTag || `way #${id}`
          const tagLines = sortedTagLines(p)
          const selected = selectedWayId != null && String(selectedWayId) === String(id)
          const key = String(id)

          return (
            <li key={key}>
              <button
                type="button"
                ref={(el) => {
                  if (el) cardRefs.current.set(key, el)
                  else cardRefs.current.delete(key)
                }}
                onClick={() => {
                  onSelectWay(selected ? null : id)
                }}
                className={[
                  'w-full rounded-xl border bg-white px-3 py-2.5 text-left text-sm shadow-sm transition-colors',
                  selected
                    ? 'border-[#4a6f8a] ring-2 ring-[#4a6f8a]/30 ring-offset-1 ring-offset-[#faf8f4]'
                    : 'border-stone-200/90 hover:border-stone-300 hover:bg-stone-50/80',
                ].join(' ')}
              >
                <div className="font-medium text-stone-800">{title}</div>
                <div className="mt-2 space-y-0.5 font-mono text-[11px] leading-snug text-stone-700">
                  {tagLines.map(([k, v]) => (
                    <div key={k} className="wrap-break-word">
                      <span className="text-stone-500">{k}:</span> <span>{v}</span>
                    </div>
                  ))}
                </div>
              </button>
            </li>
          )
        })
        .filter(Boolean)}
    </ul>
  )
}
