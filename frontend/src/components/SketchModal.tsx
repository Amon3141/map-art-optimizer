import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MdOutlineDraw, MdEdit, MdTextFields } from 'react-icons/md'
import { simplifyStroke } from '../lib/simplify'
import type { Point } from '../lib/simplify'
import { textToStrokes } from '../lib/textToStrokes'
import { applyPenSnap } from '../lib/penNodeSnap'
import { isProduction } from '../lib/appEnv'
import { MAX_STROKE_COMPONENTS, MAX_STROKE_POINTS, type InputMode, type StrokeData } from '../lib/strokeTypes'
import { findConnectedComponents } from '../lib/strokeConnectivity'
import { ModalShell } from './ModalShell'
import { SketchPreview } from './SketchPreview'

export type SketchModalProps = {
  onClose: () => void
  onConfirm: (data: StrokeData) => void
}

const MIN_DISTANCE_PX = 1.5
const MIN_DISTANCE_PEN_PX = 3
const GHOST_DASH = [6, 4]

// ────────────────────────────────────────────────────
// キャンバス描画
// ────────────────────────────────────────────────────

function drawAllStrokes(
  ctx: CanvasRenderingContext2D,
  strokes: Point[][],
  currentPts: Point[],
  ghostPt: Point | null,
  isPenMode: boolean,
  snapTarget: Point | null,
) {
  const canvas = ctx.canvas
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.lineWidth = 3

  for (let i = 0; i < strokes.length; i++) {
    const pts = strokes[i]
    if (pts.length < 2) continue
    ctx.strokeStyle = '#2d4a5e'
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)
    for (let j = 1; j < pts.length; j++) ctx.lineTo(pts[j].x, pts[j].y)
    ctx.stroke()
  }

  if (!isPenMode) return

  for (const stroke of strokes) {
    for (const p of stroke) {
      ctx.fillStyle = '#94a3b8'
      ctx.beginPath()
      ctx.arc(p.x, p.y, 3, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  for (const p of currentPts) {
    ctx.fillStyle = '#94a3b8'
    ctx.beginPath()
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2)
    ctx.fill()
  }

  if (currentPts.length >= 2) {
    ctx.strokeStyle = '#2d4a5e'
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(currentPts[0].x, currentPts[0].y)
    for (let j = 1; j < currentPts.length; j++) ctx.lineTo(currentPts[j].x, currentPts[j].y)
    ctx.stroke()
  }

  if (currentPts.length >= 1 && ghostPt) {
    const last = currentPts[currentPts.length - 1]
    ctx.strokeStyle = '#94a3b8'
    ctx.setLineDash(GHOST_DASH)
    ctx.beginPath()
    ctx.moveTo(last.x, last.y)
    ctx.lineTo(ghostPt.x, ghostPt.y)
    ctx.stroke()
    ctx.setLineDash([])
  }

  if (currentPts.length >= 1) {
    ctx.fillStyle = '#2d4a5e'
    ctx.beginPath()
    ctx.arc(currentPts[0].x, currentPts[0].y, 4, 0, Math.PI * 2)
    ctx.fill()
  }

  if (snapTarget) {
    ctx.strokeStyle = '#4a6f8a'
    ctx.fillStyle = 'rgba(74, 111, 138, 0.2)'
    ctx.lineWidth = 2
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.arc(snapTarget.x, snapTarget.y, 7, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
    ctx.lineWidth = 3
  }
}

// ────────────────────────────────────────────────────
// 説明文（1-2文、動的に変わる）
// ────────────────────────────────────────────────────

function descriptionText(inputMode: InputMode, textLength: number): string {
  if (inputMode === 'text') {
    if (textLength >= 2) {
      return 'テキストを入力すると文字の輪郭がストロークになります。文字間スペースを調整できます。'
    }
    return 'テキストを入力すると文字の輪郭がストロークになります。'
  }
  if (inputMode === 'pen') {
    return 'クリックで点を追加して形を描きます。既存の点の近くでは自動的に吸着します。複数回に分けて描いた形もそのまま使えます。'
  }
  return '指やマウスでなぞって形を描きます。複数回に分けて描いた形もそのまま使えます。'
}

// ────────────────────────────────────────────────────
// SketchModal
// ────────────────────────────────────────────────────

export function SketchModal({ onClose, onConfirm }: SketchModalProps) {
  const isPenUnsupported = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches,
    [],
  )
  const useMobileSheetAnimation = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 639px)').matches,
    [],
  )
  const prefersReducedMotion = useMemo(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )

  const shouldAnimateMobileSheet = useMobileSheetAnimation && !prefersReducedMotion

  const [exiting, setExiting] = useState(false)
  const [backdropBlurred, setBackdropBlurred] = useState(() => !shouldAnimateMobileSheet)
  const [inputMode, setInputMode] = useState<InputMode>('freehand')
  const [strokes, setStrokes] = useState<Point[][]>([])
  const [hint, setHint] = useState<string | null>(null)

  const [drawing, setDrawing] = useState(false)
  const currentRawPts = useRef<Point[]>([])

  const [penCurrentPts, setPenCurrentPts] = useState<Point[]>([])
  const penCurrentPtsRef = useRef<Point[]>([])
  const [penGhostPt, setPenGhostPt] = useState<Point | null>(null)
  const [penSnapTarget, setPenSnapTarget] = useState<Point | null>(null)

  penCurrentPtsRef.current = penCurrentPts

  const [textInput, setTextInput] = useState('')
  const [textCharSpacing, setTextCharSpacing] = useState(8)
  const [textLoading, setTextLoading] = useState(false)
  const textDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (!shouldAnimateMobileSheet) {
      setBackdropBlurred(true)
      return
    }
    const id = requestAnimationFrame(() => setBackdropBlurred(true))
    return () => cancelAnimationFrame(id)
  }, [shouldAnimateMobileSheet])

  const totalPoints = strokes.reduce((s, st) => s + st.length, 0)
  const displayPointCount =
    totalPoints + (inputMode === 'pen' ? penCurrentPts.length : 0)
  const pointsOverLimit = displayPointCount > MAX_STROKE_POINTS
  const componentCount = findConnectedComponents(strokes).length
  const componentsOverLimit = componentCount > MAX_STROKE_COMPONENTS
  const canConfirm = totalPoints >= 2 && !pointsOverLimit && !componentsOverLimit

  // ────────────────────────────────────────────────────
  // キャンバス再描画
  // ────────────────────────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || inputMode === 'text') return
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = Math.max(1, Math.floor(rect.width * dpr))
    canvas.height = Math.max(1, Math.floor(rect.height * dpr))
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    drawAllStrokes(ctx, strokes, penCurrentPts, penGhostPt, inputMode === 'pen', penSnapTarget)
  }, [strokes, penCurrentPts, penGhostPt, penSnapTarget, inputMode])

  // ────────────────────────────────────────────────────
  // 入力モード切り替え
  // ────────────────────────────────────────────────────

  const switchInputMode = (mode: InputMode) => {
    if (mode === inputMode) return
    setInputMode(mode)
    setStrokes([])
    setHint(null)
    setDrawing(false)
    currentRawPts.current = []
    setPenCurrentPts([])
    setPenGhostPt(null)
    setPenSnapTarget(null)
  }

  // ────────────────────────────────────────────────────
  // テキスト入力の処理
  // ────────────────────────────────────────────────────

  const generateTextStrokes = useCallback(
    async (text: string, spacing: number) => {
      if (!text.trim()) { setStrokes([]); return }
      setTextLoading(true)
      try {
        const result = await textToStrokes(text, spacing)
        setStrokes(result)
      } catch {
        setHint('フォントの読み込みに失敗しました。')
      } finally {
        setTextLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (inputMode !== 'text') return
    if (textDebounceRef.current) clearTimeout(textDebounceRef.current)
    textDebounceRef.current = setTimeout(() => {
      void generateTextStrokes(textInput, textCharSpacing)
    }, 300)
    return () => { if (textDebounceRef.current) clearTimeout(textDebounceRef.current) }
  }, [textInput, textCharSpacing, inputMode, generateTextStrokes])

  // ────────────────────────────────────────────────────
  // ポインターイベント（手書き）
  // ────────────────────────────────────────────────────

  const clientToPoint = (ev: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const r = canvas.getBoundingClientRect()
    return { x: ev.clientX - r.left, y: ev.clientY - r.top }
  }

  const onFreehandPointerDown = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    ev.currentTarget.setPointerCapture(ev.pointerId)
    setDrawing(true); setHint(null)
    currentRawPts.current = [clientToPoint(ev)]
  }

  const onFreehandPointerMove = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const p = clientToPoint(ev)
    const pts = currentRawPts.current
    const last = pts[pts.length - 1]
    if (last && Math.hypot(p.x - last.x, p.y - last.y) < MIN_DISTANCE_PX) return
    currentRawPts.current = [...pts, p]
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!ctx || !canvas) return
    drawAllStrokes(ctx, strokes, [], null, false, null)
    const raw = currentRawPts.current
    if (raw.length >= 2) {
      ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineWidth = 3
      ctx.strokeStyle = '#2d4a5e'; ctx.setLineDash([])
      ctx.beginPath(); ctx.moveTo(raw[0].x, raw[0].y)
      for (let i = 1; i < raw.length; i++) ctx.lineTo(raw[i].x, raw[i].y)
      ctx.stroke()
    }
  }

  const endFreehandStroke = () => {
    if (!drawing) return
    setDrawing(false)
    const raw = currentRawPts.current
    if (raw.length >= 2) setStrokes((prev) => [...prev, simplifyStroke(raw)])
    currentRawPts.current = []
  }

  // ────────────────────────────────────────────────────
  // ポインターイベント（ペンツール）
  // ────────────────────────────────────────────────────

  const resolvePenSnap = useCallback(
    (raw: Point) => {
      const { point, snapTarget } = applyPenSnap(raw, strokes, penCurrentPtsRef.current)
      return { point, snapTarget }
    },
    [strokes],
  )

  const onPenPointerDown = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    if (ev.buttons !== 1 || !ev.isPrimary) return
    setHint(null)
    const { point: p, snapTarget } = resolvePenSnap(clientToPoint(ev))
    setPenSnapTarget(snapTarget)
    setPenCurrentPts((prev) => {
      const last = prev[prev.length - 1]
      if (last && Math.hypot(p.x - last.x, p.y - last.y) < MIN_DISTANCE_PEN_PX) return prev
      return [...prev, p]
    })
  }

  const onPenPointerMove = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    if (ev.buttons !== 0) return
    const { point, snapTarget } = resolvePenSnap(clientToPoint(ev))
    setPenGhostPt(point)
    setPenSnapTarget(snapTarget)
  }

  const commitPenStroke = useCallback(() => {
    const prev = penCurrentPtsRef.current
    if (prev.length < 2) return
    setStrokes((s) => [...s, prev])
    setPenCurrentPts([])
    setPenGhostPt(null)
    setPenSnapTarget(null)
  }, [])

  const deletePreviousPenPoint = useCallback(
    () => setPenCurrentPts((prev) => prev.slice(0, -1)),
    [],
  )

  useEffect(() => {
    if (inputMode !== 'pen') return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); commitPenStroke() }
      if (e.key === 'Backspace') { e.preventDefault(); deletePreviousPenPoint() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [inputMode, commitPenStroke, deletePreviousPenPoint])

  // ────────────────────────────────────────────────────
  // 削除
  // ────────────────────────────────────────────────────

  const deleteAllStrokes = () => {
    setStrokes([]); setPenCurrentPts([]); setPenGhostPt(null); setPenSnapTarget(null)
    currentRawPts.current = []; setHint(null)
  }
  const deletePreviousStroke = () => setStrokes((prev) => prev.slice(0, -1))

  const requestClose = useCallback(() => {
    if (shouldAnimateMobileSheet) {
      setBackdropBlurred(false)
      setExiting(true)
    } else {
      onClose()
    }
  }, [onClose, shouldAnimateMobileSheet])

  const onPanelAnimationEnd = (e: React.AnimationEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || !exiting) return
    onClose()
  }

  // ────────────────────────────────────────────────────
  // 決定
  // ────────────────────────────────────────────────────

  const handleConfirm = () => {
    if (!canConfirm) {
      if (pointsOverLimit) {
        setHint(`点の数は ${MAX_STROKE_POINTS} 以下にしてください。`)
      } else {
        setHint(inputMode === 'text' ? 'テキストを入力してください。' : '線を描いてから決定してください。')
      }
      return
    }
    onConfirm({ inputMode, strokes })
    requestClose()
  }

  // ────────────────────────────────────────────────────
  // UI
  // ────────────────────────────────────────────────────

  const inputModeOptions: { mode: InputMode; label: string; icon: React.ReactNode }[] = [
    { mode: 'freehand', label: '手書き', icon: <MdOutlineDraw className="h-3.5 w-3.5" aria-hidden /> },
    ...(!isPenUnsupported
      ? [{ mode: 'pen' as InputMode, label: 'ペン', icon: <MdEdit className="h-3.5 w-3.5" aria-hidden /> }]
      : []),
    ...(!isProduction
      ? [{ mode: 'text' as InputMode, label: 'テキスト', icon: <MdTextFields className="h-3.5 w-3.5" aria-hidden /> }]
      : []),
  ]

  const hasAnyContent = strokes.length > 0 || penCurrentPts.length > 0
  const showDeleteControls = inputMode !== 'text'

  const sheetAnimClass = exiting
    ? 'max-sm:animate-sketch-sheet-out'
    : 'max-sm:animate-sketch-sheet-in'

  const backdropClassName = shouldAnimateMobileSheet
    ? [
        'max-sm:transition-[backdrop-filter]',
        exiting
          ? 'max-sm:duration-200 max-sm:ease-in'
          : 'max-sm:duration-[220ms] max-sm:ease-out',
        backdropBlurred ? 'max-sm:backdrop-blur-xs' : 'max-sm:backdrop-blur-none',
      ].join(' ')
    : ''

  return (
    <ModalShell
      open
      layout="sheet"
      backdrop="light"
      closeOnBackdropClick={false}
      closeOnEscape={false}
      ariaLabelledBy="sketch-title"
      backdropClassName={backdropClassName}
    >
      <div
        className={[
          'flex h-[92vh] w-full max-w-xl flex-col overflow-hidden rounded-t-2xl border border-stone-200/80 bg-[#fdfbf7] shadow-xl sm:h-[min(600px,90vh)] sm:rounded-2xl',
          sheetAnimClass,
        ].join(' ')}
        onAnimationEnd={onPanelAnimationEnd}
      >

        {/* ── 固定ヘッダー ── */}
        <div className="shrink-0 px-5 pt-5">
          {/* タイトル + 閉じる */}
          <div className="flex items-center justify-between">
            <h2 id="sketch-title" className="text-base font-medium text-stone-800">
              形を描く
            </h2>
            <button
              type="button"
              className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
              onClick={requestClose}
              aria-label="閉じる"
            >
              ✕
            </button>
          </div>

          {/* 入力モード */}
          <div className="mt-3 flex items-center gap-2">
            <div className="flex gap-0.5 overflow-hidden rounded-lg border border-stone-200/80 p-0.5">
              {inputModeOptions.map(({ mode, label, icon }) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => switchInputMode(mode)}
                  className={[
                    'flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
                    inputMode === mode
                      ? 'bg-stone-100 text-[#2d4a5e]'
                      : 'bg-white text-stone-500 hover:bg-stone-50 hover:text-stone-700',
                  ].join(' ')}
                >
                  {icon}
                  {label}
                </button>
              ))}
            </div>
          </div>

          <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-stone-500">
            {descriptionText(inputMode, textInput.length)}
          </p>
        </div>

        {/* ── フレキシブル中央エリア（プレビュー/キャンバス） ── */}
        <div className="min-h-0 flex-1 px-5 pt-2">
          {inputMode === 'text' ? (
            /* テキスト入力エリア */
            <div className="flex h-full flex-col gap-2">
              <input
                type="text"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="テキストを入力（日本語・英語対応）"
                className="shrink-0 w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-[#4a6f8a]"
                autoFocus
              />
              {textInput.length >= 2 && (
                <label className="shrink-0 flex flex-col gap-1">
                  <span className="text-xs text-stone-500">文字間スペース: {textCharSpacing}</span>
                  <input
                    type="range"
                    min={0}
                    max={50}
                    step={1}
                    value={textCharSpacing}
                    onChange={(e) => setTextCharSpacing(Number(e.target.value))}
                    className="accent-[#4a6f8a]"
                  />
                </label>
              )}

              {/* プレビュー: 残りスペースを全て使う */}
              <div className="relative min-h-0 flex-1">
                {textLoading ? (
                  <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-stone-300 bg-white text-sm text-stone-400">
                    フォントを読み込み中…
                  </div>
                ) : strokes.length > 0 ? (
                  <>
                    <SketchPreview strokes={strokes} strokeWidth={2} className="h-full" />
                    <p className="pointer-events-none absolute bottom-2 right-2 select-none text-[11px] text-stone-400">
                      {strokes.length} ストローク /{' '}
                      <span className={pointsOverLimit ? 'text-red-600' : ''}>
                        {displayPointCount} 点
                      </span>
                    </p>
                  </>
                ) : (
                  <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-stone-300 bg-white text-sm text-stone-400">
                    {textInput ? 'ストロークを生成中…' : 'テキストを入力するとプレビューが表示されます'}
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* 手書き / ペンツール キャンバス: 残りスペースを全て使う */
            <div className="relative h-full">
              <canvas
                ref={canvasRef}
                className="h-full w-full cursor-crosshair touch-none rounded-xl border border-dashed border-stone-300 bg-white"
                onPointerDown={inputMode === 'freehand' ? onFreehandPointerDown : onPenPointerDown}
                onPointerMove={inputMode === 'freehand' ? onFreehandPointerMove : onPenPointerMove}
                onPointerUp={inputMode === 'freehand' ? endFreehandStroke : undefined}
                onPointerCancel={inputMode === 'freehand' ? endFreehandStroke : undefined}
                onPointerLeave={
                  inputMode === 'pen'
                    ? () => {
                        setPenGhostPt(null)
                        setPenSnapTarget(null)
                      }
                    : undefined
                }
              />
              {strokes.length === 0 && penCurrentPts.length === 0 && !drawing && (
                <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-stone-400 select-none">
                  {inputMode === 'freehand' ? '指またはマウスでなぞってください' : 'クリックで点を追加します'}
                </p>
              )}
              {inputMode === 'pen' && (
                <div className="absolute bottom-2 left-2 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    disabled={penCurrentPts.length < 2}
                    onClick={commitPenStroke}
                    className="rounded-lg border border-[#4a6f8a] bg-white/95 px-2.5 py-1 text-xs font-medium text-[#4a6f8a] backdrop-blur-sm disabled:opacity-40 hover:bg-[#f3f6f8]"
                  >
                    ストローク確定
                  </button>
                  <button
                    type="button"
                    disabled={penCurrentPts.length === 0}
                    onClick={deletePreviousPenPoint}
                    className="rounded-lg border border-stone-300 bg-white/95 px-2.5 py-1 text-xs text-stone-600 backdrop-blur-sm disabled:opacity-40 hover:bg-stone-50"
                  >
                    前の点を削除
                  </button>
                </div>
              )}
              {(strokes.length > 0 || drawing || penCurrentPts.length > 0) && (
                <p className="pointer-events-none absolute bottom-2 right-2 select-none text-[11px] text-stone-400">
                  {strokes.length} ストローク /{' '}
                  <span className={pointsOverLimit ? 'text-red-600' : ''}>
                    {displayPointCount} 点
                  </span>
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── 固定フッター ── */}
        <div className="shrink-0 px-5 pb-5 pt-3">
          {pointsOverLimit && (
            <p className="mb-2 text-xs text-red-700">
              点の数が上限（{MAX_STROKE_POINTS}）を超えています。点を減らしてから決定してください。
            </p>
          )}
          {componentsOverLimit && (
            <p className="mb-2 text-xs text-red-700">
              図形のパーツ数が上限（{MAX_STROKE_COMPONENTS}）を超えています。パーツを減らしてから決定してください。
            </p>
          )}
          {hint && <p className="mb-2 text-xs text-amber-800">{hint}</p>}
          <div className="flex items-center justify-between gap-2">
            <div className="flex gap-1.5">
              {showDeleteControls && (
                <>
                  <button
                    type="button"
                    disabled={!hasAnyContent}
                    onClick={deleteAllStrokes}
                    className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 shadow-[0_1px_1px_0_rgb(0_0_0/0.04)] disabled:opacity-40 hover:bg-stone-50"
                  >
                    全て削除
                  </button>
                  <button
                    type="button"
                    disabled={strokes.length === 0}
                    onClick={deletePreviousStroke}
                    className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 shadow-[0_1px_1px_0_rgb(0_0_0/0.04)] disabled:opacity-40 hover:bg-stone-50"
                  >
                    前のストローク削除
                  </button>
                </>
              )}
            </div>
            <button
              type="button"
              onClick={handleConfirm}
              className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors ${
                canConfirm ? 'bg-[#4a6f8a] hover:bg-[#3d5f77]' : 'cursor-not-allowed bg-stone-400'
              }`}
            >
              決定
            </button>
          </div>
        </div>
      </div>
    </ModalShell>
  )
}
