const percentage = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 })

export function progressLabel(progress: number | null): string {
  return progress === null ? '目录完善中' : `${percentage.format(progress)}%`
}
