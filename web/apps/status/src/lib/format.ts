const number = new Intl.NumberFormat("en", { maximumFractionDigits: 1 })

export function formatRps(value: number | null): string {
  return value === null ? "–" : `${number.format(value)} req/s`
}

export function formatPercent(ratio: number | null): string {
  return ratio === null ? "–" : `${number.format(ratio * 100)}%`
}

export function formatMs(value: number | null): string {
  return value === null ? "–" : `${Math.round(value)} ms`
}

export function formatTime(iso: string | null): string {
  if (!iso) {
    return "never"
  }
  return new Date(iso).toLocaleTimeString("en-GB", { hour12: false })
}

export function formatSince(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(
    0,
    Math.round((now.getTime() - new Date(iso).getTime()) / 1000)
  )
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes}m`
  }
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}
