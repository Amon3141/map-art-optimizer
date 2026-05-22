/** 利用可能とみなす最小幅（px）。未満のとき MinViewportGuard を表示する。 */
export const MIN_VIEWPORT_WIDTH_PX = 320

/** Tailwind: 幅が MIN_VIEWPORT_WIDTH_PX 未満のとき（MIN_VIEWPORT_WIDTH_PX - 1 px 以下） */
export const minViewportMaxWidthClass = 'max-[319px]' as const
