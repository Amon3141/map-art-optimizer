import opentype from 'opentype.js'
import type { Point } from './simplify'

import japaneseFontUrl from '@fontsource/noto-sans-jp/files/noto-sans-jp-japanese-400-normal.woff?url'
import latinFontUrl from '@fontsource/noto-sans-jp/files/noto-sans-jp-latin-400-normal.woff?url'

const FONT_SIZE = 100
const BEZIER_STEPS = 12

const fontCache = new Map<string, opentype.Font>()

async function loadFont(url: string): Promise<opentype.Font> {
  const cached = fontCache.get(url)
  if (cached) return cached
  const res = await fetch(url)
  const buffer = await res.arrayBuffer()
  const font = opentype.parse(buffer)
  fontCache.set(url, font)
  return font
}

function sampleCubicBezier(
  x0: number, y0: number, x1: number, y1: number,
  x2: number, y2: number, x3: number, y3: number,
): Point[] {
  const pts: Point[] = []
  for (let i = 1; i <= BEZIER_STEPS; i++) {
    const t = i / BEZIER_STEPS
    const mt = 1 - t
    pts.push({
      x: mt ** 3 * x0 + 3 * mt ** 2 * t * x1 + 3 * mt * t ** 2 * x2 + t ** 3 * x3,
      y: mt ** 3 * y0 + 3 * mt ** 2 * t * y1 + 3 * mt * t ** 2 * y2 + t ** 3 * y3,
    })
  }
  return pts
}

function sampleQuadraticBezier(
  x0: number, y0: number, x1: number, y1: number, xE: number, yE: number,
): Point[] {
  const pts: Point[] = []
  for (let i = 1; i <= BEZIER_STEPS; i++) {
    const t = i / BEZIER_STEPS
    const mt = 1 - t
    pts.push({
      x: mt ** 2 * x0 + 2 * mt * t * x1 + t ** 2 * xE,
      y: mt ** 2 * y0 + 2 * mt * t * y1 + t ** 2 * yE,
    })
  }
  return pts
}

function commandsToStrokes(commands: opentype.PathCommand[]): Point[][] {
  const strokes: Point[][] = []
  let current: Point[] = []
  let cx = 0, cy = 0

  for (const cmd of commands) {
    switch (cmd.type) {
      case 'M': {
        if (current.length >= 2) strokes.push(current)
        current = [{ x: cmd.x, y: cmd.y }]
        cx = cmd.x; cy = cmd.y
        break
      }
      case 'L': {
        current.push({ x: cmd.x, y: cmd.y })
        cx = cmd.x; cy = cmd.y
        break
      }
      case 'C': {
        current.push(...sampleCubicBezier(cx, cy, cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.x, cmd.y))
        cx = cmd.x; cy = cmd.y
        break
      }
      case 'Q': {
        current.push(...sampleQuadraticBezier(cx, cy, cmd.x1, cmd.y1, cmd.x, cmd.y))
        cx = cmd.x; cy = cmd.y
        break
      }
      case 'Z': {
        if (current.length >= 2) {
          const start = current[0]
          if (Math.hypot(cx - start.x, cy - start.y) > 0.5) {
            current.push({ x: start.x, y: start.y })
          }
          strokes.push(current)
        }
        current = []
        break
      }
    }
  }

  if (current.length >= 2) strokes.push(current)
  return strokes
}

/**
 * テキストを glyph outline ポリラインに変換する。
 * @param text 入力テキスト
 * @param charSpacing 文字間の追加スペース（FONT_SIZE=100 基準の内部単位）
 * @returns 各コンターをストロークとした Point[][] 配列
 */
export async function textToStrokes(
  text: string,
  charSpacing: number,
): Promise<Point[][]> {
  if (!text.trim()) return []

  const [japFont, latFont] = await Promise.all([loadFont(japaneseFontUrl), loadFont(latinFontUrl)])

  const baseline = FONT_SIZE * 0.82
  let x = 0
  const allStrokes: Point[][] = []

  for (const char of text) {
    if (char === '\n' || char === '\r') continue

    const codePoint = char.codePointAt(0) ?? 0
    const font = codePoint <= 0x024f ? latFont : japFont
    const scaleFactor = FONT_SIZE / font.unitsPerEm

    const glyph = font.charToGlyph(char)
    const path = glyph.getPath(x, baseline, FONT_SIZE)

    if (path.commands.length > 0) {
      allStrokes.push(...commandsToStrokes(path.commands))
    }

    const advance = (glyph.advanceWidth ?? font.unitsPerEm) * scaleFactor
    x += advance + charSpacing
  }

  return allStrokes
}

export async function preloadFonts(): Promise<void> {
  await Promise.all([loadFont(japaneseFontUrl), loadFont(latinFontUrl)])
}
