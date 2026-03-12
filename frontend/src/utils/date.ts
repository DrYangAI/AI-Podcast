/**
 * Format a UTC datetime string from the backend to local time display.
 *
 * Backend stores timestamps via SQLite CURRENT_TIMESTAMP which is UTC.
 * The API returns timezone-naive ISO strings (e.g. "2026-03-11T09:39:29").
 * We append "Z" to tell JavaScript it's UTC, then toLocaleString converts to local.
 */
export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  const utcStr = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z'
  return new Date(utcStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
