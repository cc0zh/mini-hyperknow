const percentage = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 })

export function progressLabel(progress: number): string {
  return `${percentage.format(progress)}%`
}
