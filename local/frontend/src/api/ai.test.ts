// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { analyzeIncidentEvidence } from './ai'

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('AI analysis API', () => {
  it('posts to the incident AI endpoint without inventing a request body', async () => {
    const fetchMock = vi.fn(() => response({ result_type: 'FALLBACK', validated_ai: null, fallback: { incident_id: 'incident-1', reason: 'AI_DISABLED', reason_detail: 'disabled', evidence_bundle_status: 'READY', primary_evidence: [], exact_history: [], semantic_history: { attempted: false, configured: false, selected_match_count: 0, state: 'DISABLED', failure_reasons: [] }, verification: [] } }))
    vi.stubGlobal('fetch', fetchMock)

    await analyzeIncidentEvidence('incident-1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/incidents/incident-1/ai-analysis',
      expect.objectContaining({ method: 'POST', body: undefined }),
    )
  })
})
