export function recordOf(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function stringField(record: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!record) return null
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

export function booleanField(record: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!record) return null
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'boolean') return value
  }
  return null
}

export function numberField(record: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!record) return null
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return null
}

export function nestedRecord(record: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!record) return null
  for (const key of keys) {
    const value = recordOf(record[key])
    if (value) return value
  }
  return null
}

export function arrayField(record: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!record) return [] as unknown[]
  for (const key of keys) {
    const value = record[key]
    if (Array.isArray(value)) return value
  }
  return [] as unknown[]
}

export function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function titleCaseToken(value: string) {
  return value
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function statusTone(status: string): 'neutral' | 'info' | 'success' | 'warning' | 'danger' {
  switch (status) {
    case 'OPEN':
      return 'warning'
    case 'VERIFYING':
      return 'info'
    case 'VERIFIED':
      return 'success'
    case 'RECURRED':
      return 'danger'
    default:
      return 'neutral'
  }
}

export function severityTone(severity: string | null): 'neutral' | 'info' | 'success' | 'warning' | 'danger' {
  if (!severity) return 'neutral'
  const normalized = severity.toUpperCase()
  if (normalized.includes('CRITICAL') || normalized.includes('SEVERE')) return 'danger'
  if (normalized.includes('HIGH')) return 'warning'
  if (normalized.includes('MEDIUM') || normalized.includes('MODERATE')) return 'info'
  return 'neutral'
}
