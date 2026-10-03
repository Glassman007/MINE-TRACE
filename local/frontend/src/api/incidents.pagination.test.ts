import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAllIncidentsForMachine } from './incidents'

function incident(index: number) {
  return {
    incident_id: `incident-${index}`,
    machine_id: 'machine-01',
    status: 'OPEN',
    severity: null,
    owner_ref: null,
    due_state: null,
    due_time: null,
    created_at: '2026-10-03T08:00:00Z',
    updated_at: '2026-10-03T08:00:00Z',
  }
}

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => vi.unstubAllGlobals())

describe('getAllIncidentsForMachine', () => {
  it('paginates until the backend-reported machine total is exhausted', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const parsed = new URL(String(input), 'http://mine-trace.test')
      expect(parsed.pathname).toBe('/api/v1/incidents')
      expect(parsed.searchParams.get('machine_id')).toBe('machine-01')
      expect(parsed.searchParams.get('limit')).toBe('200')
      const offset = Number(parsed.searchParams.get('offset'))
      if (offset === 0) return response({ items: Array.from({ length: 200 }, (_, index) => incident(index)), total: 201, offset: 0, limit: 200 })
      if (offset === 200) return response({ items: [incident(200)], total: 201, offset: 200, limit: 200 })
      throw new Error(`unexpected offset ${offset}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const items = await getAllIncidentsForMachine('machine-01')

    expect(items).toHaveLength(201)
    expect(items[0]?.id).toBe('incident-0')
    expect(items[200]?.id).toBe('incident-200')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
