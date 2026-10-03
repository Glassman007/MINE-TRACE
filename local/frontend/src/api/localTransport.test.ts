import { afterEach, describe, expect, it, vi } from 'vitest'
import { analyzeIncidentEvidence } from './ai'
import { getBackendHealth } from './health'
import { getCurrentMachine, getCurrentMachineComponents } from './machines'
import { getOverview } from './overview'
import { getReturnToService } from './returnToService'
import { semanticSearch } from './semanticSearch'
import { getActiveSession, getSessionReport } from './sessions'
import { getSyncStatus } from './sync'

function response(body: unknown = {}) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('local API transport', () => {
  it('uses only relative local-node endpoints and never an absolute localhost backend URL', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current/components') return response({ machine_id: 'machine-1', components: [] })
      return response({})
    })
    vi.stubGlobal('fetch', fetchMock)

    await getOverview()
    await getCurrentMachine()
    await getCurrentMachineComponents()
    await getReturnToService()
    await getSyncStatus()
    await getBackendHealth()
    await getActiveSession()
    await getSessionReport('session-1')
    await semanticSearch({ query: 'hydraulic pressure warning', limit: 5 })
    await analyzeIncidentEvidence('incident-1')

    const urls = fetchMock.mock.calls.map(([input]) => String(input))
    expect(urls).toEqual(expect.arrayContaining([
      '/api/v1/overview',
      '/api/v1/machines/current',
      '/api/v1/machines/current/components',
      '/api/v1/return-to-service',
      '/api/v1/sync/status',
      '/api/v1/health',
      '/api/v1/sessions/active',
      '/api/v1/sessions/session-1/report',
      '/api/v1/semantic-search',
      '/api/v1/incidents/incident-1/ai-analysis',
    ]))
    expect(urls.every((url) => url.startsWith('/api/v1'))).toBe(true)
    expect(urls.some((url) => /https?:\/\/(localhost|127\.0\.0\.1)/.test(url))).toBe(false)
  })
})
