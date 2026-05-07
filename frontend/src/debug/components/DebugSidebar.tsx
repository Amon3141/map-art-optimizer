import { Link } from 'react-router-dom'
import { DEBUG_ROAD_TYPE_VALUES, type DebugRoadType } from '../lib/debugRoadTypes'
import { DebugWayList } from './DebugWayList'

const EMPTY_PLACEHOLDER = '（未取得）'

export type DebugPanelMode = 'text' | 'ui'

export type DebugSidebarProps = {
  loading: boolean
  error: string | null
  textDump: string
  geojson: GeoJSON.FeatureCollection | null
  panelMode: DebugPanelMode
  onPanelModeChange: (mode: DebugPanelMode) => void
  selectedWayId: number | string | null
  onSelectWay: (id: number | string | null) => void
  roadTypeInclude: Record<DebugRoadType, boolean>
  roadTypeFilterOpen: boolean
  onRoadTypeFilterOpenChange: (open: boolean) => void
  onRoadTypeChecked: (value: DebugRoadType, checked: boolean) => void
  canFetchWays: boolean
  onFetchWays: () => void
}

export function DebugSidebar({
  loading,
  error,
  textDump,
  geojson,
  panelMode,
  onPanelModeChange,
  selectedWayId,
  onSelectWay,
  roadTypeInclude,
  roadTypeFilterOpen,
  onRoadTypeFilterOpenChange,
  onRoadTypeChecked,
  canFetchWays,
  onFetchWays,
}: DebugSidebarProps) {
  const features = geojson?.features ?? []
  const fetchedWayCount = geojson != null ? features.length : null

  const emptyPlaceholder = (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <p className="px-3 py-6 text-center text-sm text-stone-500">{EMPTY_PLACEHOLDER}</p>
    </div>
  )

  return (
    <aside className="flex min-h-0 w-full flex-1 flex-col gap-4.5 overflow-hidden p-5 pb-4 lg:max-w-sm lg:h-full lg:flex-none lg:min-h-0 lg:overflow-visible lg:shrink-0 lg:py-5 lg:pl-5 lg:pr-0">
      <div className="shrink-0 flex flex-col gap-2.5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">デバッグページ</h1>
        <div
          className="rounded-xl border border-stone-200/90 bg-white/80 p-3 shadow-sm"
          role="group"
          aria-labelledby="debug-road-type-filter-heading"
        >
          <button
            type="button"
            id="debug-road-type-filter-heading"
            onClick={() => onRoadTypeFilterOpenChange(!roadTypeFilterOpen)}
            aria-expanded={roadTypeFilterOpen}
            className={[
              'flex w-full cursor-pointer items-center gap-1.5 rounded-md text-left text-xs font-medium leading-snug text-stone-600 outline-none ring-[#4a6f8a]/30 hover:text-stone-800 focus-visible:ring-2',
              roadTypeFilterOpen ? 'mb-2.5' : 'mb-0',
            ].join(' ')}
          >
            <svg
              className={[
                'size-4 shrink-0 text-stone-500 transition-transform duration-200 ease-out',
                roadTypeFilterOpen ? 'rotate-90' : 'rotate-0',
              ].join(' ')}
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden
            >
              <path
                fillRule="evenodd"
                d="M7.22 4.22a.75.75 0 0 1 1.06 0l5.25 5.25a.75.75 0 0 1 0 1.06l-5.25 5.25a.75.75 0 1 1-1.06-1.06L11.94 10 7.22 5.28a.75.75 0 0 1 0-1.06Z"
                clipRule="evenodd"
              />
            </svg>
            <span>道路種別（OSM の highway=* 値）</span>
          </button>
          {roadTypeFilterOpen ? (
            <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {DEBUG_ROAD_TYPE_VALUES.map((value) => (
                <li key={value}>
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                    <input
                      type="checkbox"
                      className="size-4 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
                      checked={roadTypeInclude[value]}
                      onChange={(e) => onRoadTypeChecked(value, e.target.checked)}
                    />
                    <span className="font-mono text-[13px]">{value}</span>
                  </label>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <button
          type="button"
          disabled={loading || !canFetchWays}
          className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-50"
          onClick={onFetchWays}
        >
          {loading ? '取得中…' : '表示範囲で道路 way を取得（最大100）'}
        </button>
      </div>

      <p className="shrink-0 text-xs leading-relaxed text-stone-600">
        範囲が広いと Overpass が重くなります。ズームしてから取得してください。{' '}
        <code className="rounded bg-stone-200/80 px-1">VITE_API_BASE</code> を frontend に設定してください。
      </p>

      {error ? <p className="shrink-0 text-sm text-red-700">{error}</p> : null}

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
        <div
          className="inline-flex w-fit shrink-0 self-start rounded-xl border border-dashed border-stone-400 bg-white p-0.5 shadow-sm"
          role="group"
          aria-label="左パネル表示モード"
        >
          <button
            type="button"
            onClick={() => onPanelModeChange('text')}
            className={[
              'rounded-[10px] px-3 py-2 text-sm font-medium transition-colors',
              panelMode === 'text'
                ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                : 'text-stone-600 hover:text-stone-800',
            ].join(' ')}
          >
            テキスト
          </button>
          <button
            type="button"
            onClick={() => onPanelModeChange('ui')}
            className={[
              'rounded-[10px] px-3 py-2 text-sm font-medium transition-colors',
              panelMode === 'ui'
                ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                : 'text-stone-600 hover:text-stone-800',
            ].join(' ')}
          >
            一覧
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
          {fetchedWayCount != null ? (
            <p className="shrink-0 text-[11px] leading-none text-stone-400 tabular-nums">
              取得した道路 way: {fetchedWayCount} 件
            </p>
          ) : null}

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] lg:min-h-[200px]">
            {panelMode === 'text' ? (
              textDump ? (
                <pre className="min-h-0 flex-1 overflow-auto p-3 text-[11px] leading-snug text-stone-800">
                  {textDump}
                </pre>
              ) : (
                emptyPlaceholder
              )
            ) : geojson ? (
              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                <DebugWayList
                  features={features}
                  selectedWayId={selectedWayId}
                  onSelectWay={onSelectWay}
                />
              </div>
            ) : (
              emptyPlaceholder
            )}
          </div>
        </div>
      </div>

      <Link
        to="/"
        className="mt-auto shrink-0 text-sm font-medium text-[#4a6f8a] underline-offset-2 hover:underline"
      >
        ← アプリに戻る
      </Link>
    </aside>
  )
}
