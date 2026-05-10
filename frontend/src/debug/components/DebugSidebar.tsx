import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  DEBUG_HIGHWAY_EXCLUDE_OPTIONS,
  type DebugHighwayExcludeSelection,
  type DebugHighwayExcludeType,
} from '../lib/debugHighwayExclude'
import { HIGHLIGHT_OSM_MERGE, HIGHLIGHT_SNAP_MERGE } from '../lib/debugHighlightColors'
import type { GraphBuildOptionsPayload, GraphPreviewResponse, GraphStepMetrics } from '../lib/graphPreview'
import type { DebugMapViewMode } from './DebugMapPanel'
import { DebugWayList } from './DebugWayList'

const EMPTY_PLACEHOLDER = '（未取得）'

export type DebugPanelMode = 'text' | 'ui'

export type DebugSidebarProps = {
  loading: boolean
  error: string | null
  textDump: string
  geojson: GeoJSON.FeatureCollection | null
  waysFetchedCount: number | null
  highwayExclude: DebugHighwayExcludeSelection
  onHighwayExcludeChecked: (value: DebugHighwayExcludeType, checked: boolean) => void
  roadFilterOpen: boolean
  onRoadFilterOpenChange: (open: boolean) => void
  panelMode: DebugPanelMode
  onPanelModeChange: (mode: DebugPanelMode) => void
  selectedWayId: number | string | null
  onSelectWay: (id: number | string | null) => void
  onFetchWays: () => void
  mapViewMode: DebugMapViewMode
  onMapViewModeChange: (mode: DebugMapViewMode) => void
  graphOptions: GraphBuildOptionsPayload
  onGraphOptionsChange: (next: GraphBuildOptionsPayload) => void
  graphLoading: boolean
  graphError: string | null
  graphPreview: GraphPreviewResponse | null
}

export function DebugSidebar({
  loading,
  error,
  textDump,
  geojson,
  waysFetchedCount,
  highwayExclude,
  onHighwayExcludeChecked,
  roadFilterOpen,
  onRoadFilterOpenChange,
  panelMode,
  onPanelModeChange,
  selectedWayId,
  onSelectWay,
  onFetchWays,
  mapViewMode,
  onMapViewModeChange,
  graphOptions,
  onGraphOptionsChange,
  graphLoading,
  graphError,
  graphPreview,
}: DebugSidebarProps) {
  const features = geojson?.features ?? []
  const fetchedWayCount = geojson != null ? features.length : null
  const hasRoadData = features.length > 0
  const fetchCountLabel =
    waysFetchedCount != null && fetchedWayCount != null
      ? `表示 ${fetchedWayCount} / 取得 ${waysFetchedCount}`
      : null

  const emptyPlaceholder = (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <p className="px-3 py-6 text-center text-sm text-stone-500">{EMPTY_PLACEHOLDER}</p>
    </div>
  )

  const toggleOpt = (key: keyof GraphBuildOptionsPayload, checked: boolean) => {
    if (
      key === 'snap_epsilon_m' ||
      key === 'road_merge_distance_m' ||
      key === 'road_merge_angle_deg' ||
      key === 'road_merge_min_overlap_m' ||
      key === 'road_merge_min_overlap_ratio' ||
      key === 'road_merge_anchor_delta_m' ||
      key === 'prune_chain_accum_angle_deg'
    ) {
      return
    }
    onGraphOptionsChange({ ...graphOptions, [key]: checked })
  }

  return (
    <aside className="flex min-h-0 w-full flex-1 flex-col gap-4.5 overflow-hidden p-5 pb-4 lg:max-w-sm lg:h-full lg:flex-none lg:min-h-0 lg:overflow-visible lg:shrink-0 lg:py-5 lg:pl-5 lg:pr-0">
      <div className="shrink-0 flex flex-col gap-2.5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-800">デバッグページ</h1>
        <div
          className="inline-flex w-full shrink-0 rounded-xl border border-dashed border-stone-400 bg-white p-0.5 shadow-sm"
          role="group"
          aria-label="マップ表示モード"
        >
          <button
            type="button"
            onClick={() => onMapViewModeChange('osm')}
            className={[
              'min-w-0 flex-1 rounded-[10px] px-2 py-2 text-xs font-medium transition-colors sm:text-sm',
              mapViewMode === 'osm'
                ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                : 'text-stone-600 hover:text-stone-800',
            ].join(' ')}
          >
            OSMモード
          </button>
          <button
            type="button"
            onClick={() => onMapViewModeChange('graph')}
            className={[
              'min-w-0 flex-1 rounded-[10px] px-2 py-2 text-xs font-medium transition-colors sm:text-sm',
              mapViewMode === 'graph'
                ? 'bg-[#f3f6f8] text-[#2d4a5e] shadow-inner'
                : 'text-stone-600 hover:text-stone-800',
            ].join(' ')}
          >
            グラフモード
          </button>
        </div>
        <div
          className="rounded-xl border border-stone-200/90 bg-white/80 p-3 shadow-sm"
          role="group"
          aria-labelledby="debug-highway-exclude-heading"
        >
          <button
            type="button"
            id="debug-highway-exclude-heading"
            onClick={() => onRoadFilterOpenChange(!roadFilterOpen)}
            aria-expanded={roadFilterOpen}
            className={[
              'flex w-full cursor-pointer items-center gap-1.5 rounded-md text-left text-xs font-medium leading-snug text-stone-600 outline-none ring-[#4a6f8a]/30 hover:text-stone-800 focus-visible:ring-2',
              roadFilterOpen ? 'mb-2.5' : 'mb-0',
            ].join(' ')}
          >
            <svg
              className={[
                'size-4 shrink-0 text-stone-500 transition-transform duration-200 ease-out',
                roadFilterOpen ? 'rotate-90' : 'rotate-0',
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
            <span>除外する highway=* 値</span>
          </button>
          {roadFilterOpen ? (
            <div className="flex flex-col gap-2.5">
              <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {DEBUG_HIGHWAY_EXCLUDE_OPTIONS.map((value) => (
                  <li key={value}>
                    <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                      <input
                        type="checkbox"
                        className="size-4 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
                        checked={highwayExclude[value]}
                        onChange={(e) => onHighwayExcludeChecked(value, e.target.checked)}
                      />
                      <span className="font-mono text-[13px]">{value}</span>
                    </label>
                  </li>
                ))}
              </ul>
              {fetchCountLabel ? (
                <p className="text-[11px] font-medium text-stone-600">{fetchCountLabel}</p>
              ) : null}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          disabled={loading}
          className="rounded-xl bg-[#4a6f8a] px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-50"
          onClick={onFetchWays}
        >
          {loading ? '取得中…' : '表示範囲で道路 way を取得'}
        </button>
      </div>

      <p className="shrink-0 text-xs leading-relaxed text-stone-600">
        範囲が広いと Overpass が重くなります。ズームしてから取得してください。{' '}
        <code className="rounded bg-stone-200/80 px-1">VITE_API_BASE</code> を frontend に設定してください。
      </p>

      {error ? <p className="shrink-0 text-sm text-red-700">{error}</p> : null}

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
        {mapViewMode === 'graph' ? (
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
            <div className="shrink-0 rounded-xl border border-stone-200/90 bg-white/90 p-3 shadow-sm">
              <p className="mb-2 text-xs font-medium text-stone-700">グラフ構築オプション</p>
              {graphLoading && hasRoadData ? (
                <p className="mb-2 text-[11px] text-stone-500">更新中…</p>
              ) : null}
              <ul className="flex flex-col gap-3 text-sm text-stone-800">
                <GraphOptionBlock
                  title="同じ OSM node id の頂点をつなぐ"
                  checked={graphOptions.connect_osm_node_ids}
                  onToggle={(c) => toggleOpt('connect_osm_node_ids', c)}
                  result={
                    <ConnectOsmMetrics
                      m={graphPreview?.step_metrics}
                      graphLoading={graphLoading}
                      hasRoadData={hasRoadData}
                    />
                  }
                />
                <GraphOptionBlock
                  title="距離が近い頂点をまとめる"
                  checked={graphOptions.snap_endpoints}
                  onToggle={(c) => toggleOpt('snap_endpoints', c)}
                  result={
                    <SnapMetrics
                      m={graphPreview?.step_metrics}
                      graphLoading={graphLoading}
                      hasRoadData={hasRoadData}
                    />
                  }
                  footer={
                    <label className="mt-1 flex items-center gap-2 text-xs text-stone-600">
                      <span className="shrink-0">ε (m)</span>
                      <input
                        type="number"
                        min={0.05}
                        max={500}
                        step={0.5}
                        disabled={!graphOptions.snap_endpoints}
                        value={graphOptions.snap_epsilon_m}
                        onChange={(e) =>
                          onGraphOptionsChange({
                            ...graphOptions,
                            snap_epsilon_m: Number(e.target.value) || graphOptions.snap_epsilon_m,
                          })
                        }
                        className="w-full rounded-lg border border-stone-200 bg-[#faf8f4] px-2 py-1 font-mono text-[13px] disabled:opacity-45"
                      />
                    </label>
                  }
                />
                <GraphOptionBlock
                  title="重複・並行道路を代表線へマージ"
                  checked={graphOptions.merge_duplicate_roads}
                  onToggle={(c) => toggleOpt('merge_duplicate_roads', c)}
                  result={
                    <RoadMergeMetrics
                      m={graphPreview?.step_metrics}
                      graphLoading={graphLoading}
                      hasRoadData={hasRoadData}
                    />
                  }
                  footer={
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-stone-600">
                      <NumberOptionInput
                        label="距離 m"
                        disabled={!graphOptions.merge_duplicate_roads}
                        value={graphOptions.road_merge_distance_m}
                        min={0.5}
                        max={100}
                        step={0.5}
                        onChange={(v) => onGraphOptionsChange({ ...graphOptions, road_merge_distance_m: v })}
                      />
                      <NumberOptionInput
                        label="角度 °"
                        disabled={!graphOptions.merge_duplicate_roads}
                        value={graphOptions.road_merge_angle_deg}
                        min={0.5}
                        max={45}
                        step={0.5}
                        onChange={(v) => onGraphOptionsChange({ ...graphOptions, road_merge_angle_deg: v })}
                      />
                      <NumberOptionInput
                        label="重なり m"
                        disabled={!graphOptions.merge_duplicate_roads}
                        value={graphOptions.road_merge_min_overlap_m}
                        min={0}
                        max={500}
                        step={1}
                        onChange={(v) => onGraphOptionsChange({ ...graphOptions, road_merge_min_overlap_m: v })}
                      />
                      <NumberOptionInput
                        label="重なり率"
                        disabled={!graphOptions.merge_duplicate_roads}
                        value={graphOptions.road_merge_min_overlap_ratio}
                        min={0}
                        max={1}
                        step={0.05}
                        onChange={(v) =>
                          onGraphOptionsChange({ ...graphOptions, road_merge_min_overlap_ratio: v })
                        }
                      />
                      <NumberOptionInput
                        label="anchor δ m"
                        disabled={!graphOptions.merge_duplicate_roads}
                        value={graphOptions.road_merge_anchor_delta_m}
                        min={0.05}
                        max={50}
                        step={0.5}
                        onChange={(v) => onGraphOptionsChange({ ...graphOptions, road_merge_anchor_delta_m: v })}
                      />
                    </div>
                  }
                />
                <GraphOptionBlock
                  title="道路の交差で線を分割する"
                  checked={graphOptions.split_intersections}
                  onToggle={(c) => toggleOpt('split_intersections', c)}
                  result={
                    <SplitMetrics
                      m={graphPreview?.step_metrics}
                      graphLoading={graphLoading}
                      hasRoadData={hasRoadData}
                    />
                  }
                />
                <GraphOptionBlock
                  title="不要な中間ノードを削除"
                  checked={graphOptions.remove_redundant_chain_vertices}
                  onToggle={(c) => toggleOpt('remove_redundant_chain_vertices', c)}
                  result={
                    <PruneChainsMetrics
                      m={graphPreview?.step_metrics}
                      graphLoading={graphLoading}
                      hasRoadData={hasRoadData}
                    />
                  }
                  footer={
                    <label className="mt-1 flex items-center gap-2 text-xs text-stone-600">
                      <span className="shrink-0">累積角（°）</span>
                      <input
                        type="number"
                        min={0.5}
                        max={179}
                        step={0.5}
                        disabled={!graphOptions.remove_redundant_chain_vertices}
                        value={graphOptions.prune_chain_accum_angle_deg}
                        onChange={(e) =>
                          onGraphOptionsChange({
                            ...graphOptions,
                            prune_chain_accum_angle_deg:
                              Number(e.target.value) || graphOptions.prune_chain_accum_angle_deg,
                          })
                        }
                        className="w-full rounded-lg border border-stone-200 bg-[#faf8f4] px-2 py-1 font-mono text-[13px] disabled:opacity-45"
                      />
                    </label>
                  }
                />
              </ul>
              {graphPreview ? (
                <p className="mt-3 border-t border-stone-200 pt-3 text-xs tabular-nums text-stone-600">
                  グラフ全体：ノード {graphPreview.stats.node_count ?? '—'} · エッジ{' '}
                  {graphPreview.stats.edge_count ?? '—'}
                </p>
              ) : null}
            </div>
            {!hasRoadData ? (
              <p className="shrink-0 text-sm text-stone-500">
                道路データを取得すると、グラフモードで自動的に構築されます。
              </p>
            ) : null}
            {graphError ? <p className="shrink-0 text-sm text-red-700">{graphError}</p> : null}
          </div>
        ) : (
          <>
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
          </>
        )}
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

function GraphOptionBlock({
  title,
  checked,
  onToggle,
  result,
  footer,
}: {
  title: string
  checked: boolean
  onToggle: (c: boolean) => void
  result?: ReactNode
  footer?: ReactNode
}) {
  return (
    <li className="rounded-lg border border-stone-100 bg-[#faf8f4]/90 px-2 py-2">
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-0.5 size-4 shrink-0 rounded border-stone-300 text-[#4a6f8a] focus:ring-[#4a6f8a]/40"
          checked={checked}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <button
          type="button"
          className="cursor-pointer text-left text-sm font-medium leading-snug text-stone-800 hover:text-stone-950"
          onClick={() => onToggle(!checked)}
        >
          {title}
        </button>
      </div>
      {footer}
      {checked && result != null ? (
        <div className="mt-2 border-t border-stone-200/80 pt-2">{result}</div>
      ) : null}
    </li>
  )
}

function NumberOptionInput({
  label,
  disabled,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  disabled: boolean
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="truncate text-[10px]">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || value)}
        className="w-full rounded-lg border border-stone-200 bg-[#faf8f4] px-2 py-1 font-mono text-[13px] disabled:opacity-45"
      />
    </label>
  )
}

function PruneChainsMetrics({
  m,
  graphLoading,
  hasRoadData,
}: {
  m: GraphStepMetrics | undefined
  graphLoading: boolean
  hasRoadData: boolean
}) {
  if (!hasRoadData) {
    return <p className="text-[11px] text-stone-400">道路データを取得すると表示されます</p>
  }
  const d = m?.prune_chains
  if (d == null) {
    return (
      <p className="text-[11px] text-stone-400">{graphLoading ? '計算中…' : '再計算後に表示されます'}</p>
    )
  }
  return (
    <div className="space-y-1">
      <ul className="space-y-0.5 font-mono text-[11px] text-stone-600">
        <li>
          累積角の閾値: {d.angle_accum_threshold_deg ?? '—'}°（符号付き折れの積み上げ）
        </li>
        <li>除去した頂点: {d.vertices_removed ?? '—'}</li>
      </ul>
      <p className="text-[10px] leading-snug text-stone-500">
        マップには簡略化<strong className="font-medium text-stone-700">後</strong>のグラフが表示されています。
      </p>
    </div>
  )
}

function RoadMergeMetrics({
  m,
  graphLoading,
  hasRoadData,
}: {
  m: GraphStepMetrics | undefined
  graphLoading: boolean
  hasRoadData: boolean
}) {
  if (!hasRoadData) {
    return <p className="text-[11px] text-stone-400">道路データを取得すると表示されます</p>
  }
  const d = m?.road_merge
  if (d == null) {
    return (
      <p className="text-[11px] text-stone-400">{graphLoading ? '計算中…' : '再計算後に表示されます'}</p>
    )
  }
  return (
    <div className="space-y-1">
      <ul className="space-y-0.5 font-mono text-[11px] text-stone-600">
        <li>候補ペア: {d.candidate_pairs ?? '—'}</li>
        <li>採用 directed edge: {d.directed_edges ?? '—'}</li>
        <li>向き反転: {d.direction_repaired_edges ?? '—'}</li>
        <li>outdegree 削除: {d.outdegree_pruned_edges ?? '—'}</li>
        <li>cycle 削除: {d.cycle_edges_removed ?? '—'}</li>
        <li>削除した source edge: {d.source_edges_removed ?? '—'}</li>
        <li>追加 anchor: {d.anchors_created ?? '—'}</li>
        <li>付け替えた incident edge: {d.incident_edges_remapped ?? '—'}</li>
      </ul>
      <p className="text-[10px] leading-snug text-stone-500">
        「追加 anchor」は代表線上に新設した頂点の本数です。synthetic ノードは交差分割由来と区別せず、
        <code className="rounded bg-stone-200/80 px-0.5">source_osm_node_ids</code> が空の頂点としてマップ上も同じ扱いです。
      </p>
    </div>
  )
}

function ConnectOsmMetrics({
  m,
  graphLoading,
  hasRoadData,
}: {
  m: GraphStepMetrics | undefined
  graphLoading: boolean
  hasRoadData: boolean
}) {
  if (!hasRoadData) {
    return <p className="text-[11px] text-stone-400">道路データを取得すると表示されます</p>
  }
  const d = m?.connect_osm
  if (d == null) {
    return (
      <p className="text-[11px] text-stone-400">{graphLoading ? '計算中…' : '再計算後に表示されます'}</p>
    )
  }
  return (
    <div className="space-y-1">
      <ul className="space-y-0.5 font-mono text-[11px] text-stone-600">
        <li>まとめたグループ数: {d.osm_id_groups_merged ?? '—'}</li>
        <li>グラフから除いた頂点: {d.graph_vertices_removed_by_merge ?? '—'}</li>
        <li>OSM id で合体した頂点（マップでは黄色のノード）: {d.merged_vertex_count ?? '—'}</li>
      </ul>
      <p className="text-[10px] leading-snug text-stone-500">
        マップの
        <strong className="font-medium" style={{ color: HIGHLIGHT_OSM_MERGE }}>
          黄色のノード
        </strong>
        が、この合体が起きた頂点です。
      </p>
    </div>
  )
}

function SplitMetrics({
  m,
  graphLoading,
  hasRoadData,
}: {
  m: GraphStepMetrics | undefined
  graphLoading: boolean
  hasRoadData: boolean
}) {
  if (!hasRoadData) {
    return <p className="text-[11px] text-stone-400">道路データを取得すると表示されます</p>
  }
  const d = m?.split
  if (d == null) {
    return (
      <p className="text-[11px] text-stone-400">{graphLoading ? '計算中…' : '再計算後に表示されます'}</p>
    )
  }
  return (
    <div className="space-y-1">
      <ul className="space-y-0.5 font-mono text-[11px] text-stone-600">
        <li>交差処理の適用回数: {d.intersection_splits_applied ?? '—'}</li>
        <li>追加した交点頂点: {d.new_vertices_from_split ?? '—'}</li>
      </ul>
      <p className="text-[10px] leading-snug text-stone-500">
        マップの<strong className="font-medium text-rose-700">朱色のノード</strong>が、
        交差で線が分割されて新しく追加された頂点です。
      </p>
    </div>
  )
}

function SnapMetrics({
  m,
  graphLoading,
  hasRoadData,
}: {
  m: GraphStepMetrics | undefined
  graphLoading: boolean
  hasRoadData: boolean
}) {
  if (!hasRoadData) {
    return <p className="text-[11px] text-stone-400">道路データを取得すると表示されます</p>
  }
  const d = m?.snap
  if (d == null) {
    return (
      <p className="text-[11px] text-stone-400">{graphLoading ? '計算中…' : '再計算後に表示されます'}</p>
    )
  }
  return (
    <div className="space-y-1">
      <ul className="space-y-0.5 font-mono text-[11px] text-stone-600">
        <li>しきい値 ε (m): {d.epsilon_m ?? '—'}</li>
        <li>まとめた近接グループ: {d.snap_clusters ?? '—'}</li>
        <li>グラフから除いた頂点: {d.vertices_merged_by_snap ?? '—'}</li>
      </ul>
      <p className="text-[10px] leading-snug text-stone-500">
        マップの
        <strong className="font-medium" style={{ color: HIGHLIGHT_SNAP_MERGE }}>
          緑のノード
        </strong>
        が、距離 snap で代表点にまとめた頂点です。
      </p>
    </div>
  )
}
