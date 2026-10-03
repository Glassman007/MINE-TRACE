import { describe, expect, it } from 'vitest'
import { formatDateTime, localInputToIso, machineIdentity } from './machineFormatting'

describe('machine formatting', () => {
  it('uses display name, then asset code, then shortened UUID for identity', () => {
    const base = {
      id: '12345678-aaaa-bbbb-cccc-123456789abc',
      display_name: null,
      asset_code: null,
      machine_type: null,
      manufacturer: null,
      model: null,
      site_name: null,
      site_area: null,
    }

    expect(machineIdentity({ ...base, display_name: 'Loader 7', asset_code: 'LD-7' })).toBe('Loader 7')
    expect(machineIdentity({ ...base, asset_code: 'LD-7' })).toBe('LD-7')
    expect(machineIdentity(base)).toBe('12345678…')
  })

  it('renders offset timestamps as the correct instant in a requested timezone', () => {
    const formatted = formatDateTime('2026-10-03T11:00:00+05:30', 'UTC')
    const expectedHour = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'UTC',
    }).format(new Date('2026-10-03T05:30:00Z'))

    expect(formatted).toBe(expectedHour)
  })

  it('converts a local datetime filter into a timezone-aware ISO instant', () => {
    const iso = localInputToIso('2026-10-03T11:00')
    expect(iso).toMatch(/^2026-10-03T\d{2}:\d{2}:00\.000Z$/)
  })
})
