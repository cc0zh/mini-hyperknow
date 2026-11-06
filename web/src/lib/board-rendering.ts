import type { KatexOptions } from 'katex'

/** Unicode Chinese labels are intentional in this classroom. Keep all other
 * LaTeX strictness and the independent trust boundary. KaTeX documents this
 * error-code handler at https://katex.org/docs/options.html. */
export const formulaOptions: KatexOptions = {
  displayMode: true, throwOnError: true, trust: false, maxExpand: 500, maxSize: 20,
  strict: code => code === 'unicodeTextInMathMode' ? 'ignore' : 'error',
}

/** Fit measured ink, never enlarge it or turn an unmeasured hidden node into 0. */
export function fitToWidth(naturalWidth: number, availableWidth: number): number {
  if (![naturalWidth, availableWidth].every(value => Number.isFinite(value) && value > 0)) return 1
  return Math.min(1, availableWidth / naturalWidth)
}

/** Preserve natural diagram size; CSS may shrink, but never enlarge it. */
export function naturalSvgWidth(viewBox: string | null): number | null {
  if (!viewBox?.trim()) return null
  const dimensions = viewBox.trim().split(/[\s,]+/).map(Number)
  if (dimensions.length !== 4 || !dimensions.every(Number.isFinite)) return null
  return dimensions[2] > 0 && dimensions[3] > 0 ? dimensions[2] : null
}
