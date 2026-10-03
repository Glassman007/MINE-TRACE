import type { MachineSummary } from '../api/machines'

export function shortId(value: string, length = 8) {
  return value.length <= length ? value : `${value.slice(0, length)}…`
}

export function machineIdentity(machine: MachineSummary) {
  return machine.display_name ?? machine.asset_code ?? shortId(machine.id)
}

export function machineProduct(machine: MachineSummary) {
  const value = [machine.manufacturer, machine.model].filter(Boolean).join(' · ')
  return value || null
}

export function machineSite(machine: MachineSummary) {
  const value = [machine.site_name, machine.site_area].filter(Boolean).join(' · ')
  return value || null
}

export function formatDateTime(value: string | null | undefined, timeZone?: string) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  }).format(date)
}

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return String(value)
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value / 1024
  let unitIndex = 0
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024
    unitIndex += 1
  }
  return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`
}

export function isoToLocalInput(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

export function localInputToIso(value: string) {
  if (!value) return undefined
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString()
}
