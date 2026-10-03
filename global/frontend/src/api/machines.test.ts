// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getMachineIncidents, getMachineSessions, getMachines } from './machines'

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('global machine API contracts', () => {
  it('uses the backend fleet filter names from OpenAPI', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => jsonResponse({ items: [], total: 0, offset: 24, limit: 12 }))
    vi.stubGlobal('fetch', fetchMock)

    await getMachines({ offset: 24, limit: 12, search: 'loader west', site: 'North Pit', machine_type: 'WHEEL_LOADER', model: 'WL-X' })

    const call = fetchMock.mock.calls[0]
    const url = new URL(String(call?.[0]), 'http://mine-trace.test')
    expect(url.pathname).toBe('/api/v1/machines')
    expect(url.searchParams.get('offset')).toBe('24')
    expect(url.searchParams.get('limit')).toBe('12')
    expect(url.searchParams.get('search')).toBe('loader west')
    expect(url.searchParams.get('site')).toBe('North Pit')
    expect(url.searchParams.get('machine_type')).toBe('WHEEL_LOADER')
    expect(url.searchParams.get('model')).toBe('WL-X')
    expect(url.searchParams.has('site_name')).toBe(false)
  })

  it('reads synchronized sessions and incidents from their global endpoints', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/sessions')) return jsonResponse({ machine_id: 'machine/01', items: [], total: 0, offset: 10, limit: 5 })
      return jsonResponse({ items: [], total: 0, offset: 10, limit: 5 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await getMachineSessions('machine/01', { offset: 10, limit: 5 })
    await getMachineIncidents('machine/01', { offset: 10, limit: 5 })

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('/api/v1/machines/machine%2F01/sessions?offset=10&limit=5')
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe('/api/v1/machines/machine%2F01/incidents?offset=10&limit=5')
  })
})
