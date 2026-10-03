// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { analyzeFleet } from './ai'

afterEach(() => vi.unstubAllGlobals())

describe('Groq fleet AI API', () => {
  it('runs only when explicitly invoked and posts the generated request contract', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'DEGRADED', provider: 'groq', reason: 'missing_groq_api_key' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })))
    vi.stubGlobal('fetch', fetchMock)

    expect(fetchMock).not.toHaveBeenCalled()
    await analyzeFleet({ prompt: 'Compare the evidence', incident_ids: ['incident-1'], semantic_query: 'hydraulic whine', semantic_top_k: 3 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/ai/analyze',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ prompt: 'Compare the evidence', incident_ids: ['incident-1'], semantic_query: 'hydraulic whine', semantic_top_k: 3 }),
      }),
    )
  })
})
