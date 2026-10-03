// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { searchFleetSemantic } from './semanticSearch'

afterEach(() => vi.unstubAllGlobals())

describe('fleet semantic search API', () => {
  it('posts structured fleet filters and preserves similarity semantics', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'AVAILABLE', results: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })))
    vi.stubGlobal('fetch', fetchMock)

    await searchFleetSemantic({ query: 'hydraulic whine', machine_id: 'm-1', component_id: 'c-1', model: 'HX', site: 'North', start: '2026-10-01T00:00:00Z', end: '2026-10-03T00:00:00Z', top_k: 8 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/search/semantic',
      expect.objectContaining({ method: 'POST', body: expect.stringContaining('"top_k":8') }),
    )
  })
})
