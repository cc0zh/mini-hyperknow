/** Preserve natural diagram size; CSS may shrink, but never enlarge it. */
export function naturalSvgWidth(viewBox: string | null): number | null {
  if (!viewBox?.trim()) return null
  const dimensions = viewBox.trim().split(/[\s,]+/).map(Number)
  if (dimensions.length !== 4 || !dimensions.every(Number.isFinite)) return null
  return dimensions[2] > 0 && dimensions[3] > 0 ? dimensions[2] : null
}
